"""Scenario drivers for the golden baseline tests.

Each scenario function:
1. Loads a real config from config/*.yml
2. Configures the test doubles (canned waveforms, download returns, etc.)
3. Calls the alarm's run_alarm() at a fixed time (T0)

After run_alarm returns, the test harness captures what happened (Icinga calls,
messages sent, DB writes) and compares against the frozen baseline.

Scenario types:
- "representative": exercises each alarm's default offline path (usually an
  early OK/WARNING due to missing external data)
- "critical": provides crafted fixtures that trigger a CRITICAL detection and
  the full send sequence (message + DB write + cleanup)

To add a new scenario:
1. Write a function taking (doubles, load_config) and calling run_alarm
2. Register it in the SCENARIOS dict at the bottom of this file as
   "<Module>-<variant>": ("<Module>", driver_fn). The frozen JSON will live at
   baselines/<Module>/<Module>-<variant>.json.
3. Run: REGEN_BASELINES=1 pytest -m integration -k "your_scenario"
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Stream, Trace, UTCDateTime
from obspy.core.event import Catalog, Event, Magnitude as EventMagnitude, Origin, ResourceIdentifier

from obspy import read as read_stream
from obspy import read_events, read_inventory

from tests._harness.snapshot_utils import T0

# Fixtures dir holding test-only configs (e.g. KENI_Infrasound.yml) and recorded
# waveform data used to drive real-detection scenarios offline.
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_CONFIGS_DIR = FIXTURES_DIR / "configs"
FIXTURE_DATA_DIR = FIXTURES_DIR / "data"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_fixture_config(config_name):
    """Load a test-only config from tests/fixtures/configs via the real loader.

    Temporarily points ``CONFIGS_DIR`` at the fixtures config dir so
    ``setup_utils.load_config`` (and its Infrasound enrichment) run exactly as in
    production, then restores the original value. Keeps these test configs out of
    the repo ``config/`` directory.
    """
    from volc_alarms.utils import setup_utils

    original = os.environ.get("CONFIGS_DIR")
    os.environ["CONFIGS_DIR"] = str(FIXTURE_CONFIGS_DIR)
    try:
        return setup_utils.load_config(config_name)
    finally:
        if original is None:
            os.environ.pop("CONFIGS_DIR", None)
        else:
            os.environ["CONFIGS_DIR"] = original

def _clean_test_db():
    """Remove the sqlite file the un-doubled DB helpers touch, for determinism.

    ``can_send`` / ``record_send`` / ``filter_dataframe`` are doubled in-memory,
    but a few read paths (e.g. Tremor's ``pd.read_sql_query``) hit the real
    sqlite file named by ``DB_FILE``. Deleting it first guarantees those reads
    see an empty, freshly-created table every time.
    """
    db_file = os.environ.get("DB_FILE")
    if db_file:
        p = Path(db_file)
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(p) + suffix)
            if f.exists():
                f.unlink()


def _make_trace(nslc, T1, data, sampling_rate=100.0):
    net, sta, loc, chan = nslc.split(".")
    tr = Trace(data=np.asarray(data, dtype="float64"))
    tr.stats.network = net
    tr.stats.station = sta
    tr.stats.location = loc
    tr.stats.channel = chan
    tr.stats.sampling_rate = sampling_rate
    tr.stats.starttime = T1
    return tr


# ---------------------------------------------------------------------------
# RSAM
#
# All five scenarios replay ONE real recorded Pavlof event (2026-09-28 20:40
# UTC) through the Pavlof_RSAM config; each makes one small config tweak to
# steer run_alarm down a different outcome branch. The recorded event, as-is,
# is a genuine CRITICAL detection (arrestor quiet, 4 of 6 source stations over
# threshold); scaling thresholds or the arrestor threshold reaches the elevated
# / arrested / normal branches, and zeroing channels reaches the data-missing
# branch.
# ---------------------------------------------------------------------------

RSAM_EVENT_T0 = UTCDateTime("2026-09-28T20:40:00")
RSAM_EVENT_FIXTURE = FIXTURE_DATA_DIR / "rsam_Pavlof_20260928T2040.mseed"


def _pavlof_waveform_factory(zero_all_but=None):
    """Waveform factory serving the recorded Pavlof event window.

    Returns a copy of the recorded stream trimmed to the requested [T1, T2].
    run_alarm calls download_waveforms twice (source stations, then arrestor);
    the recording contains both, so selecting by the requested NSLC list serves
    each call correctly. ``zero_all_but`` zero-fills all but that many of the
    requested channels -- used for the data-missing branch.
    """
    recorded = read_stream(str(RSAM_EVENT_FIXTURE))

    def _factory(nslc_list, T1, T2, **_):
        st = Stream()
        for nslc in nslc_list:
            sel = recorded.select(id=nslc)
            if sel:
                st += sel.copy().trim(T1, T2)
        if zero_all_but is not None:
            for tr in st[zero_all_but:]:
                tr.data = np.zeros_like(tr.data)
        return st

    return _factory


def _scale_thresholds(config, factor):
    """Multiply every source-station and arrestor RSAM threshold by ``factor``."""
    for sta in config.rsam_stations:
        sta["value"] = sta["value"] * factor
    config.arrestor["value"] = config.arrestor["value"] * factor


def rsam_critical(doubles, load_config):
    """Recorded Pavlof event -> CRITICAL RSAM detection + full send.

    Unmodified Pavlof_RSAM config: the arrestor is quiet and 4 of 6 source
    stations exceed their thresholds, so run_alarm reaches CRITICAL and the full
    figure -> Mattermost -> email -> DB record -> cleanup -> Icinga sequence.
    """
    config = _load_fixture_config("Pavlof_RSAM")
    from volc_alarms import RSAM

    doubles.waveform_factory = _pavlof_waveform_factory()
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, RSAM_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def rsam_elevated(doubles, load_config):
    """Thresholds x2 -> too few over full threshold, enough over half -> WARNING.

    Same real waveforms; doubling every threshold means <min_sta stations exceed
    the full level (so no CRITICAL) but >=min_sta still exceed half -> the
    'RSAM elevated!' WARNING branch.
    """
    config = _load_fixture_config("Pavlof_RSAM")
    from volc_alarms import RSAM

    _scale_thresholds(config, 2.0)
    doubles.waveform_factory = _pavlof_waveform_factory()
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, RSAM_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def rsam_arrested(doubles, load_config):
    """Lowered arrestor threshold -> arrestor 'loud' vetoes a real detection.

    The recorded arrestor RMS (~50) is quiet against its real threshold (200),
    but lowering that threshold to 10 makes the arrestor count as loud while the
    source stations still exceed their levels -> the 'RSAM normal (arrested)'
    WARNING branch (a regional/teleseismic-style veto).
    """
    config = _load_fixture_config("Pavlof_RSAM")
    from volc_alarms import RSAM

    config.arrestor["value"] = 10
    doubles.waveform_factory = _pavlof_waveform_factory()
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, RSAM_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def rsam_normal(doubles, load_config):
    """Thresholds x10 -> nothing exceeds even half threshold -> OK 'RSAM normal'.

    Same real waveforms with every threshold raised far above the observed RMS,
    so the alarm resolves to the baseline OK state.
    """
    config = _load_fixture_config("Pavlof_RSAM")
    from volc_alarms import RSAM

    _scale_thresholds(config, 10.0)
    doubles.waveform_factory = _pavlof_waveform_factory()
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, RSAM_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def rsam_data_missing(doubles, load_config):
    """Only 2 live source channels (< min_sta) -> 'RSAM data missing!' WARNING.

    Zero-filling all but two source channels leaves fewer than ``min_sta`` with
    any data, so run_alarm reports the data-missing WARNING.
    """
    config = _load_fixture_config("Pavlof_RSAM")
    from volc_alarms import RSAM

    doubles.waveform_factory = _pavlof_waveform_factory(zero_all_but=2)
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, RSAM_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Infrasound
#
# All four scenarios drive the SAME recorded KENI array event through the KENI
# config; each makes one small config tweak to steer run_alarm down a different
# outcome branch (data-quality WARNING, below-amplitude OK, wrong-back-azimuth
# no-detection, and a genuine CRITICAL detection + send).
# ---------------------------------------------------------------------------

# Recorded real KENI array event (2026-05-14 22:56 UTC). The MiniSEED fixture
# spans a wide pad around the event; the waveform factory returns the slice
# run_alarm asks for, so the whole LTS array-processing path runs offline and
# deterministically. All four Infrasound scenarios drive this same real event
# through the KENI config, differing only in a small config tweak that steers
# run_alarm down each of its outcome branches.
INFRASOUND_EVENT_T0 = UTCDateTime("2026-05-14T22:56:00")
INFRASOUND_EVENT_FIXTURE = FIXTURE_DATA_DIR / "infrasound_KENI_20260514T2256.mseed"


def _keni_waveform_factory(zero_all_but=None):
    """Build a waveform factory serving the recorded KENI event window.

    Returns a copy of the recorded stream trimmed to the requested [T1, T2].
    If ``zero_all_but`` is given (a count), all but that many channels are
    zero-filled -- used to drive the data-quality (not-enough-channels) branch.
    """
    recorded = read_stream(str(INFRASOUND_EVENT_FIXTURE))

    def _factory(nslc_list, T1, T2, **_):
        st = recorded.copy().trim(T1, T2)
        if zero_all_but is not None:
            for tr in st[zero_all_but:]:
                tr.data = np.zeros_like(tr.data)
        return st

    return _factory


def infrasound_not_enough_channels(doubles, load_config):
    """Only 2 live KENI channels (< min_chan) -> 'Not enough channels!' WARNING.

    QC_data drops the zero-filled traces, leaving fewer than ``min_chan``, so
    run_alarm exits at the data-quality gate before any array processing.
    """
    config = _load_fixture_config("KENI_Infrasound")
    from volc_alarms import Infrasound

    doubles.waveform_factory = _keni_waveform_factory(zero_all_but=2)
    doubles.patch_figure_builder(Infrasound, "make_figure")
    Infrasound.run_alarm(config, INFRASOUND_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def infrasound_below_amplitude(doubles, load_config):
    """Real event but a high min_pa -> 'not enough channels exceeding amplitude'.

    The array data passes QC, but with every target's ``min_pa`` raised above
    the observed peak pressure, too few channels exceed the amplitude gate, so
    run_alarm returns OK before inverting for back-azimuth.
    """
    config = _load_fixture_config("KENI_Infrasound")
    from volc_alarms import Infrasound

    # Observed per-channel peaks are ~0.6-1.0 Pa; 1.5 Pa suppresses all of them.
    for target in config.targets:
        target["min_pa"] = 1.5

    doubles.waveform_factory = _keni_waveform_factory()
    doubles.patch_figure_builder(Infrasound, "make_figure")
    Infrasound.run_alarm(config, INFRASOUND_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def infrasound_wrong_backazimuth(doubles, load_config):
    """Coherent airwave, but from a back-azimuth no target accepts -> no detection.

    The recorded event's LTS solution points at ~216-221 deg. Here we pin every
    target's ``back_azimuth`` to ~40 deg (roughly opposite the arrival) while
    leaving ``min_pa`` untouched, so the array data still clears QC and the
    amplitude gate and LTS runs -- but every target's azimuth filter rejects the
    wave, so run_alarm reaches the end with no CRITICAL detection. This exercises
    the full array-processing path and the "coherent wave from an unmonitored
    direction" outcome. Pre-setting ``back_azimuth`` is preserved by
    ``get_target_backazimuth`` (which only fills it when absent).
    """
    config = _load_fixture_config("KENI_Infrasound")
    from volc_alarms import Infrasound

    for target in config.targets:
        target["back_azimuth"] = 40.0

    doubles.waveform_factory = _keni_waveform_factory()
    doubles.patch_figure_builder(Infrasound, "make_figure")
    Infrasound.run_alarm(config, INFRASOUND_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def infrasound_critical(doubles, load_config):
    """Recorded KENI array event -> CRITICAL airwave detection + full send.

    The unmodified KENI config accepts the ~216-221 deg arrival at Fourpeaked
    and Katmai, driving the complete detection + send sequence for each.
    """
    config = _load_fixture_config("KENI_Infrasound")
    from volc_alarms import Infrasound

    doubles.waveform_factory = _keni_waveform_factory()
    doubles.patch_figure_builder(Infrasound, "make_figure")
    Infrasound.run_alarm(config, INFRASOUND_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Tremor
#
# The Tremor alarm accumulates state: each run reads prior located events from
# the tremor DB table, runs the (real) enveloc solver on freshly-downloaded
# waveforms, merges the two, and branches on how many minutes of the lookback
# window are covered plus an RSAM amplitude gate. All scenarios replay ONE
# recorded Pavlof event (2026-09-29 10:35 UTC) through the real solver; the
# branch is set by how many prior events we seed into the DB (via the real
# record_tremor_event_ids) and small config tweaks.
# ---------------------------------------------------------------------------
TREMOR_EVENT_T0 = UTCDateTime("2026-09-29T10:35:00")
TREMOR_EVENT_FIXTURE = FIXTURE_DATA_DIR / "tremor_Pavlof_20260929T1035.mseed"
TREMOR_GRID_FIXTURE = FIXTURE_DATA_DIR / "Pavlof_Tremor_grid.npz"


def _load_tremor_config():
    """Load the Pavlof tremor config pointed at the committed grid fixture.

    Sets an absolute ``grid_file`` (so run_enveloc reuses the precomputed
    travel-time grid) and a large ``max_scatter`` so a real located event is
    never dropped by the bootstrap-scatter filter -- the scatter estimate is the
    only non-deterministic part of enveloc and it is not captured in the baseline.
    """
    config = _load_fixture_config("Pavlof_tremor")
    config.grid_file = TREMOR_GRID_FIXTURE.resolve()
    config.max_scatter = 1e9
    return config


def _tremor_waveform_factory(*, zero_all_but=None, noise=False):
    """Waveform factory serving the recorded Pavlof tremor window.

    ``zero_all_but`` zero-fills all but that many channels (data-missing branch).
    ``noise`` replaces every channel with seeded low-amplitude white noise that
    passes QC but yields zero enveloc detections (the elevated-but-no-new-events
    branch).
    """
    recorded = read_stream(str(TREMOR_EVENT_FIXTURE))
    if noise:
        rng = np.random.default_rng(1234)
        for tr in recorded:
            tr.data = (rng.standard_normal(tr.stats.npts) * 5.0).astype("float64")

    def _factory(nslc_list, T1, T2, **_):
        st = Stream()
        for nslc in nslc_list:
            sel = recorded.select(id=nslc)
            if sel:
                st += sel.copy().trim(T1, T2)
        if zero_all_but is not None:
            for tr in st[zero_all_but:]:
                tr.data = np.zeros_like(tr.data)
        return st

    return _factory


def _seed_tremor_events(config, n, spacing_min=5):
    """Seed ``n`` prior tremor events into the DB (via record_tremor_event_ids),
    spaced ``spacing_min`` apart and ending just before the real 10:30 detection."""
    from volc_alarms.utils import alarming

    # UTC-aware timestamps: record_tremor_event_ids -> iso_utc calls
    # .astimezone(UTC), which would shift a tz-naive time by the pinned local
    # zone offset and push these events outside the lookback window.
    last_prior = pd.Timestamp("2026-09-29 10:25:00", tz="UTC")
    times = [last_prior - pd.Timedelta(minutes=spacing_min * i) for i in range(n)][::-1]
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(times, utc=True),
            "latitude": [55.40] * n,
            "longitude": [-161.82] * n,
            "depth": [5.0] * n,
            "volcano": [config.volcano] * n,
        }
    )
    alarming.record_tremor_event_ids(df, test=False)


def tremor_data_missing(doubles, load_config):
    """Only 2 live channels (< min_sta) -> 'Data missing!' WARNING.

    Zero-filling all but two channels fails qc_checks/min_sta, so run_alarm exits
    before running enveloc.
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    doubles.waveform_factory = _tremor_waveform_factory(zero_all_but=2)
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_normal(doubles, load_config):
    """Real detection, empty prior DB -> short duration -> OK 'Seismicity normal'."""
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    doubles.waveform_factory = _tremor_waveform_factory()
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_elevated(doubles, load_config):
    """Real detection + 4 seeded prior events -> 'Elevated seismicity' WARNING.

    Puts the covered duration in [threshold/2, threshold), the elevated band.
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    _seed_tremor_events(config, n=4)
    doubles.waveform_factory = _tremor_waveform_factory()
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_elevated_no_new_events(doubles, load_config):
    """Prior events keep duration high, but enveloc finds nothing new -> WARNING.

    Seeds 9 prior events (duration >= threshold) and feeds noise so enveloc
    locates zero new events, exercising the 'elevated seismicity but no new
    events' branch (Tremor/Swarm detection WARNING, no send).
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    # Lower the RSAM gate so it passes (else the low-amplitude branch, which is
    # checked first, would catch this case); the point here is the separate
    # "duration high but zero NEW events" branch.
    config.rsam_threshold = 0
    _seed_tremor_events(config, n=9)
    doubles.waveform_factory = _tremor_waveform_factory(noise=True)
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_low_amplitude(doubles, load_config):
    """Duration >= threshold + new event, but RSAM gate fails -> low-amplitude WARNING.

    Seeds 8 prior events so duration >= threshold with a new real detection, but
    the recorded RSAM on rsam_station (~35) is below the real threshold (180), so
    run_alarm reports 'Tremor/Swarm detection, but low amplitude' (no send).
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    _seed_tremor_events(config, n=8)
    doubles.waveform_factory = _tremor_waveform_factory()
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_missing_rsam_station(doubles, load_config):
    """rsam_station absent -> gate can't block, alarm still fires + error alert.

    Pointing rsam_station at a channel not in the stream makes run_alarm set
    rsam_test above threshold (so a real detection is not vetoed) and send an
    'Error' alert about the missing station. With 8 seeded prior events + the new
    detection this reaches CRITICAL and additionally emits the missing-station
    error email.
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    config.rsam_station = "AV.NONE..BHZ"  # not in the recording
    _seed_tremor_events(config, n=8)
    doubles.waveform_factory = _tremor_waveform_factory()
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def tremor_critical(doubles, load_config):
    """Real detection + prior events + passing RSAM gate -> CRITICAL + send.

    Seeds 8 prior events (duration >= threshold with the new detection present)
    and lowers rsam_threshold so the recorded RSAM (~35) clears the gate, so
    run_alarm reaches CRITICAL and the full send sequence + tremor-DB update.
    """
    _clean_test_db()
    config = _load_tremor_config()
    from volc_alarms import Tremor

    config.rsam_threshold = 20  # recorded PS1A RSAM ~35 clears this gate
    _seed_tremor_events(config, n=8)
    doubles.waveform_factory = _tremor_waveform_factory()
    doubles.patch_figure_builder(Tremor.figure, "make_figure")
    Tremor.run_alarm(config, TREMOR_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Lightning
#
# Lightning's input is JSON from the volcview "avorecent" API. Three scenarios
# replay a real pared API pull (tests/fixtures/data/lightning_avorecent.json)
# through the REAL download_lightning parser (only the curl/os.popen call is
# faked) and the normal cron path (find_nearest_volcano against the volcano
# list), differing only in which recorded storm window T0 selects. The remaining
# scenarios drive control-flow / DB-state branches with small crafted inputs.
#
# The real-fixture scenarios point VOLCANO_LIST at the shipped volcano_list_avo.csv
# because it carries the per-alarm "Lightning" opt-out column (Y/N) that the
# packaged placeholder volcano_list.csv lacks. That column is what makes the
# ignore path real: strokes the API attributes to an N volcano are reassigned to
# the nearest Y volcano and dropped when none is within dist2.
# ---------------------------------------------------------------------------
# Volcano list carrying the Lightning Y/N ignore column (Edgecumbe=Y; Duncan
# Canal, Tlevak Strait, Behm Canal-Rudyerd Bay = N).
LIGHTNING_VOLCANO_LIST = files("volc_alarms.data").joinpath("volcano_list_avo.csv")

# Capture the genuine download_lightning at import time, BEFORE the harness's
# install() doubles the module attribute. The real-fixture scenarios reinstall
# this so the production parser runs (we fake only its curl/os.popen source).
from volc_alarms.alarms.Lightning import detection as _lightning_detection  # noqa: E402

_REAL_DOWNLOAD_LIGHTNING = _lightning_detection.download_lightning

# Each real-fixture scenario has its OWN single-storm fixture file, because
# run_alarm only trims strokes on the lower bound (time > T0 - duration) -- there
# is no upper bound (in production the API only returns recent strokes). One file
# per storm keeps each scenario isolated; T0 is set just after that storm's last
# stroke so the 1-hour look-back captures the whole storm and nothing else.
LIGHTNING_CRITICAL_FIXTURE = FIXTURE_DATA_DIR / "lightning_critical.json"
LIGHTNING_DISTAL_FIXTURE = FIXTURE_DATA_DIR / "lightning_distal.json"
LIGHTNING_IGNORED_FIXTURE = FIXTURE_DATA_DIR / "lightning_ignored.json"

LIGHTNING_CRITICAL_T0 = UTCDateTime("2026-08-31T20:59:00")     # Edgecumbe proximal (last stroke 20:58:38)
LIGHTNING_DISTAL_T0 = UTCDateTime("2026-09-21T00:00:00")       # far Edgecumbe (last stroke 23:59:59)
LIGHTNING_IGNORED_T0 = UTCDateTime("2026-09-23T18:26:00")      # Behm Canal N (last stroke 18:25:50)


def _run_lightning_from_fixture(doubles, fixture_path, T0_event):
    """Drive Lightning.run_alarm over a recorded single-storm API fixture.

    Runs the REAL download_lightning: os.popen is faked to return the fixture
    JSON (so the genuine parse + column-rename path runs), and VOLCANO_LIST
    points at volcano_list_avo.csv so the Y/N ignore column is active. The figure
    builder is stubbed to a placeholder; everything else uses the shared doubles.
    """
    import io

    from volc_alarms import Lightning
    from volc_alarms.alarms.Lightning import detection as lightning_detection

    mp = doubles.monkeypatch
    fixture_text = Path(fixture_path).read_text(encoding="utf-8")

    # Re-install the REAL parser (install() had doubled it) so the fixture flows
    # through the production download_lightning, then fake only its curl source.
    # run_alarm calls download_lightning via the name imported into the Lightning
    # package namespace, so patch both the package and the detection module.
    mp.setattr(lightning_detection, "download_lightning", _REAL_DOWNLOAD_LIGHTNING)
    mp.setattr(Lightning, "download_lightning", _REAL_DOWNLOAD_LIGHTNING)

    def _fake_popen(_cmd, *a, **k):
        return io.StringIO(fixture_text)

    mp.setattr(lightning_detection.os, "popen", _fake_popen)
    # download_lightning builds a curl string from these; values are irrelevant
    # since popen is faked, but must exist so the f-string formats.
    mp.setenv("LIGHTNING_URL", "https://example.test/vv-api/lightningApi/avorecent")
    mp.setenv("API_USERNAME", "test")
    mp.setenv("API_PASSWORD", "test")
    # Activate the Y/N ignore column via the fuller shipped volcano list.
    mp.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))

    config = load_config_lightning()
    doubles.patch_figure_builder(Lightning, "plot_fig")
    Lightning.run_alarm(config, T0_event, test_flag=False, mm_flag=True, icinga_flag=True)


def load_config_lightning():
    """Load the real config/Lightning.yml (no test-only enrichment needed)."""
    from volc_alarms.utils import setup_utils

    return setup_utils.load_config("Lightning")


def lightning_critical(doubles, load_config):
    """Real Edgecumbe storm, proximal first stroke -> CRITICAL + full send.

    T0 selects the 2026-08-31 20-21Z window: 17 strokes reassign to Edgecumbe
    (a Y volcano), first stroke ~8 km (proximal), so run_alarm reaches CRITICAL
    and the full figure -> Mattermost -> email -> DB record -> cleanup sequence.
    The lone API-labeled Duncan Canal stroke reattributes past dist2 and drops.
    """
    _clean_test_db()
    _run_lightning_from_fixture(doubles, LIGHTNING_CRITICAL_FIXTURE, LIGHTNING_CRITICAL_T0)


def lightning_distal(doubles, load_config):
    """Real storm, all strokes distal (first > dist1) -> WARNING, no send.

    T0 selects the 2026-09-20 23Z-09-21 00Z window: 37 strokes reassign to
    Edgecumbe but the nearest is ~35 km (outside dist1), so the first new stroke
    is distal and run_alarm reports the 'Distal Lightning Detection!' WARNING
    without sending. Duncan Canal / Tlevak strokes (N volcanoes) drop out.
    """
    _clean_test_db()
    _run_lightning_from_fixture(doubles, LIGHTNING_DISTAL_FIXTURE, LIGHTNING_DISTAL_T0)


def lightning_ignored_volcano(doubles, load_config):
    """Proximal strokes at an IGNORED (N) volcano -> suppressed -> OK.

    T0 selects the 2026-09-23 17:30-18:30Z window: 10 strokes the API attributes
    to Behm Canal-Rudyerd Bay, 8 of them proximal (down to ~8 km) -- an obvious
    would-be CRITICAL. But Behm Canal is Lightning=N, so find_nearest_volcano
    reassigns every stroke to the nearest Y volcano (>100 km away) and the dist2
    filter drops them all, leaving zero new strokes -> OK 'No new strokes'. This
    is the explicit proof the ignore column works.
    """
    _clean_test_db()
    _run_lightning_from_fixture(doubles, LIGHTNING_IGNORED_FIXTURE, LIGHTNING_IGNORED_T0)


def lightning_no_data(doubles, load_config):
    """API returns an empty stroke list -> OK 'No new strokes detected'."""
    config = load_config("Lightning")
    from volc_alarms import Lightning

    doubles.download_returns["download_lightning"] = pd.DataFrame(
        columns=["id", "time", "latitude", "longitude", "dataSource", "api_vname", "api_vlat", "api_vlon", "api_vdist"]
    )
    Lightning.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def lightning_api_error(doubles, load_config):
    """download_lightning returns None (API failure) -> Volcview-API WARNING."""
    config = load_config("Lightning")
    from volc_alarms import Lightning

    doubles.download_returns["download_lightning"] = None
    Lightning.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def lightning_all_seen(doubles, load_config):
    """Proximal strokes, but the DB already recorded every id -> OK, no re-alert.

    Models the DB-backed recent-state suppression: the API returns strokes that
    would be a CRITICAL proximal detection, but filter_dataframe (backed by the
    alarm-history DB) reports zero NEW ids, so run_alarm resolves to OK 'No new
    strokes' without sending. The filter_dataframe double is given a callable so
    both of run_alarm's filter passes (full set, then per-volcano) see the same
    'already seen' verdict.
    """
    config = load_config("Lightning")
    from volc_alarms import Lightning

    strokes = pd.DataFrame(
        {
            "id": ["L1", "L2", "L3"],
            "time": pd.to_datetime(
                ["2024-12-31 23:20:00", "2024-12-31 23:30:00", "2024-12-31 23:40:00"]
            ),
            "api_vdist": [4.0, 6.0, 9.0],
            "api_vname": ["Pavlof", "Pavlof", "Pavlof"],
            "api_vlat": [55.420, 55.420, 55.420],
            "api_vlon": [-161.887, -161.887, -161.887],
            "latitude": [55.40, 55.41, 55.42],
            "longitude": [-161.85, -161.86, -161.87],
            "dataSource": ["EN", "EN", "EN"],
        }
    )
    doubles.download_returns["download_lightning"] = strokes

    # Every id is "already seen": new_df is empty, df is unchanged. Returned for
    # each filter_dataframe call regardless of the (full vs per-volcano) input.
    def _all_seen(df, **_):
        return df.iloc[0:0].copy(), df

    doubles.filter_dataframe_result = _all_seen
    # force_flag defaults False -> find_nearest_volcano runs against the default
    # volcano list; the crafted coords sit near Pavlof so assignment succeeds.
    Lightning.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# NOAA_CIMSS
#
# The critical scenario replays a real recorded alert (a Spurr ash alert,
# NOAA report 448880, 2026-09-29) through the real detection path offline:
#   - noaa_cimss_vvapi_spurr.json    the volcview-API alert list (one alert)
#   - noaa_cimss_alert_448880.html   the scraped alert-detail page
# download_cimss_vv_api runs for real with os.popen faked to serve the JSON, so
# the genuine pd.read_json + format/find_nearest/ignore filtering runs. The
# scrape double returns a BeautifulSoup of the recorded HTML, so the real
# process_alert_soup parsing (instrument, timestamp+radiative-center match,
# status/type, aid, image links) runs. get_cimss_image is a harness no-op and
# plot_fig is stubbed -- the figure render is covered by test_figure.py.
# ---------------------------------------------------------------------------
NOAA_CIMSS_T0 = UTCDateTime("2026-09-29T23:00:00")
NOAA_CIMSS_JSON_FIXTURE = FIXTURE_DATA_DIR / "noaa_cimss_vvapi_spurr.json"
NOAA_CIMSS_HTML_FIXTURE = FIXTURE_DATA_DIR / "noaa_cimss_alert_448880.html"
NOAA_CIMSS_EVENT_ID = "448880"

# Capture the genuine download_cimss_vv_api before install() doubles it.
from volc_alarms.alarms.NOAA_CIMSS import detection as _cimss_detection  # noqa: E402

_REAL_DOWNLOAD_CIMSS = _cimss_detection.download_cimss_vv_api


def _install_real_cimss_download(doubles, json_fixture):
    """Reinstall the real download_cimss_vv_api, faking only its os.popen curl.

    Serves the fixture JSON text so the genuine pd.read_json + downstream
    format/find_nearest/ignore path runs, recorded as one download call.
    """
    import io

    from volc_alarms import NOAA_CIMSS
    from volc_alarms.alarms.NOAA_CIMSS import detection as cimss_detection

    mp = doubles.monkeypatch
    text = Path(json_fixture).read_text(encoding="utf-8")

    mp.setattr(cimss_detection, "download_cimss_vv_api", _REAL_DOWNLOAD_CIMSS)
    mp.setattr(NOAA_CIMSS, "download_cimss_vv_api", _REAL_DOWNLOAD_CIMSS)
    mp.setattr(cimss_detection.os, "popen", lambda *a, **k: io.StringIO(text))
    mp.setenv("NOAA_CIMSS_URL", "https://example.test/vv-api/noaa_cimss")
    mp.setenv("API_USERNAME", "test")
    mp.setenv("API_PASSWORD", "test")
    # Pin the volcano list so find_nearest_volcano / create_message resolve the
    # same nearest-volcano set regardless of test order (the NOAA opt-out column
    # also lives here). Keeps the baseline deterministic.
    mp.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))


def _install_cimss_scrape_soup(doubles):
    """Install a scrape_cimss_alert double returning the recorded HTML as soup.

    run_alarm calls scrape_cimss_alert via the name imported into the NOAA_CIMSS
    package, so patch both the package and the detection module.
    """
    from bs4 import BeautifulSoup

    from volc_alarms import NOAA_CIMSS
    from volc_alarms.alarms.NOAA_CIMSS import detection as cimss_detection

    html = NOAA_CIMSS_HTML_FIXTURE.read_bytes()

    def _scrape(alert, *a, **k):
        return BeautifulSoup(html, "html.parser")

    doubles.monkeypatch.setattr(cimss_detection, "scrape_cimss_alert", _scrape)
    doubles.monkeypatch.setattr(NOAA_CIMSS, "scrape_cimss_alert", _scrape)


def noaa_cimss_api_error(doubles, load_config):
    """download_cimss_vv_api returns None (API failure) -> Volcview-API WARNING."""
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    doubles.download_returns["download_cimss_vv_api"] = None
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def noaa_cimss_no_new_alerts(doubles, load_config):
    """Alerts present but all far from any volcano -> OK 'No new recent alerts'.

    A crafted alert list with a single alert in the open Pacific (> max_distance
    from every volcano), so the distance filter drops it before the loop.
    """
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    doubles.download_returns["download_cimss_vv_api"] = pd.DataFrame(
        [
            {
                "alert_header": "POSSIBLE VOLCANIC ASH CLOUD FOUND",
                "alert_type": "ash",
                "alert_url": "https://example.test/alert/report/999001",
                "method": "test",
                "lon_rc": -140.0,
                "lat_rc": 40.0,  # mid-Pacific, far from any AVO volcano
                "object_date_time": "2026-09-29 12:00:00",
            }
        ]
    )
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def noaa_cimss_webpage_error(doubles, load_config):
    """Real near-volcano alert, but the alert page won't scrape -> webpage WARNING."""
    _clean_test_db()
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    _install_real_cimss_download(doubles, NOAA_CIMSS_JSON_FIXTURE)
    doubles.download_returns["scrape_cimss_alert"] = None  # scrape fails -> None
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def noaa_cimss_already_processed(doubles, load_config):
    """The recorded alert, but already in the DB -> OK 'No new recent alerts'."""
    _clean_test_db()
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS
    from volc_alarms.utils import alarming

    # Seed the NOAA_id into the real (non-test) sent_events table so
    # already_processed() short-circuits the loop.
    conn = alarming.get_conn(test=False)
    try:
        table = alarming.resolve_table_name(test=False)
        conn.execute(
            f"INSERT INTO {table} (alarm_id, event_id, volcano, process_time, send_time) "
            f"VALUES (?, ?, ?, ?, ?)",
            (config.alarm_name, NOAA_CIMSS_EVENT_ID, "Spurr",
             "2026-09-29T14:30:38Z", "2026-09-29T23:00:00Z"),
        )
    finally:
        conn.close()

    _install_real_cimss_download(doubles, NOAA_CIMSS_JSON_FIXTURE)
    _install_cimss_scrape_soup(doubles)
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def noaa_cimss_critical(doubles, load_config):
    """Recorded Spurr ash alert -> CRITICAL detection + full send.

    Runs the real download_cimss_vv_api over the recorded single-alert JSON and
    the real process_alert_soup over the recorded alert HTML (returned by the
    scrape double), so find_nearest_volcano places it at Spurr, the parser reads
    instrument/status/type/aid, and create_message renders the alert before the
    full Mattermost -> DB record -> cleanup -> Icinga sequence. plot_fig is
    stubbed (render covered by test_figure.py); get_cimss_image is a harness no-op.
    """
    _clean_test_db()
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    _install_real_cimss_download(doubles, NOAA_CIMSS_JSON_FIXTURE)
    _install_cimss_scrape_soup(doubles)
    doubles.patch_figure_builder(NOAA_CIMSS, "plot_fig")
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def noaa_cimss_ignored_volcano(doubles, load_config):
    """An alert at an IGNORED (NOAA=N) volcano -> suppressed -> OK.

    A crafted ash alert whose radiative center sits on Tana, which is NOAA=N in
    volcano_list_avo.csv (its per-alarm opt-out column). find_nearest_volcano
    assigns it to Tana, then check_ignore_volcano drops it, so the loop never
    runs and run_alarm resolves to OK 'No new recent NOAA CIMSS alerts'. Points
    VOLCANO_LIST at the avo list because the packaged placeholder volcano_list.csv
    lacks the NOAA column (the ignore path would be a no-op with it). This is the
    explicit proof the NOAA opt-out column works.
    """
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_cimss_vv_api"] = pd.DataFrame(
        [
            {
                "alert_header": "POSSIBLE VOLCANIC ASH CLOUD FOUND",
                "alert_type": "ash",
                "alert_url": "https://example.test/alert/report/999002",
                "method": "test",
                "lon_rc": -169.758,   # Tana (NOAA=N in volcano_list_avo.csv)
                "lat_rc": 52.839,
                "object_date_time": "2026-09-29 12:00:00",
            }
        ]
    )
    NOAA_CIMSS.run_alarm(config, NOAA_CIMSS_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Pilot_Report
#
# The urgent/non_urgent scenarios replay a real recorded PIREP shapefile (a
# Shishaldin volcanic-ash report, 2026-09-11 00:39 UTC) through the real
# detection path offline. The download double returns ("OK", <real ZipFile>) so
# the genuine shapefile parse (pirep_archive_to_dataframe) + find_nearest_volcano
# + check_volcano_mention (the "VA SHISHALDIN" trigger) all run. VOLCANO_LIST
# points at volcano_list_avo.csv so the PIREP opt-in column is active. plot_fig
# is stubbed; the render is covered by test_figure.py.
# ---------------------------------------------------------------------------
PIREP_T0 = UTCDateTime("2026-09-11T00:45:00")  # ~6 min after the recorded report
PIREP_ZIP_FIXTURE = FIXTURE_DATA_DIR / "pilot_report_Shishaldin_20260911T0039.zip"
PIREP_EVENT_ID = "202609110000-KMSC-UBUS01-PIREP_20260911003900_54.5885_-163.7547"


def _pirep_zipfile():
    """Fresh ZipFile handle for the recorded PIREP shapefile fixture."""
    import zipfile

    return zipfile.ZipFile(PIREP_ZIP_FIXTURE, "r")


def pilot_report_critical(doubles, load_config):
    """Recorded urgent Shishaldin ash PIREP -> CRITICAL + full send.

    The download double returns the real shapefile ZIP, so run_alarm parses it,
    places the report ~23 km from Shishaldin (< the 200 km config distance), and
    check_volcano_mention triggers on 'VA SHISHALDIN'. URGENT='T' in the report
    makes it CRITICAL and drives the full send sequence. plot_fig is stubbed.
    """
    _clean_test_db()
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_pilot_reports"] = ("OK", _pirep_zipfile())
    doubles.patch_figure_builder(Pilot_Report, "plot_fig")
    Pilot_Report.run_alarm(config, PIREP_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def pilot_report_non_urgent(doubles, load_config):
    """Same recorded report, URGENT flipped to 'F' -> WARNING + send (not CRITICAL).

    Wraps the real pirep_archive_to_dataframe to set URGENT='F' on the parsed
    rows, so the triggering report still sends but as a WARNING (is_critical is
    False), exercising the non-urgent branch of run_alarm.
    """
    _clean_test_db()
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_pilot_reports"] = ("OK", _pirep_zipfile())

    real_parse = Pilot_Report.pirep_archive_to_dataframe

    def _non_urgent_parse(T0_, cfg, archive):
        df = real_parse(T0_, cfg, archive)
        df["URGENT"] = "F"
        return df

    doubles.monkeypatch.setattr(Pilot_Report, "pirep_archive_to_dataframe", _non_urgent_parse)
    doubles.patch_figure_builder(Pilot_Report, "plot_fig")
    Pilot_Report.run_alarm(config, PIREP_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def pilot_report_api_error(doubles, load_config):
    """download_pilot_reports returns ('WARNING', None) -> PIREP API error WARNING."""
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report

    doubles.download_returns["download_pilot_reports"] = ("WARNING", None)
    Pilot_Report.run_alarm(config, PIREP_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def pilot_report_no_reports(doubles, load_config):
    """download returns ('OK', None) (no shapefile) -> OK 'No new pilot reports'."""
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report

    doubles.download_returns["download_pilot_reports"] = ("OK", None)
    Pilot_Report.run_alarm(config, PIREP_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def pilot_report_already_processed(doubles, load_config):
    """The recorded report, but already in the DB -> OK 'No new pilot reports'."""
    _clean_test_db()
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report
    from volc_alarms.utils import alarming

    conn = alarming.get_conn(test=False)
    try:
        table = alarming.resolve_table_name(test=False)
        conn.execute(
            f"INSERT INTO {table} (alarm_id, event_id, volcano, process_time, send_time) "
            f"VALUES (?, ?, ?, ?, ?)",
            (config.alarm_name, PIREP_EVENT_ID, "Shishaldin",
             "2026-09-11T00:39:00Z", "2026-09-11T00:45:00Z"),
        )
    finally:
        conn.close()

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_pilot_reports"] = ("OK", _pirep_zipfile())
    doubles.patch_figure_builder(Pilot_Report, "plot_fig")
    Pilot_Report.run_alarm(config, PIREP_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# SO2
# ---------------------------------------------------------------------------
def so2_representative(doubles, load_config):
    """Default download returns (None, None) -> webpage error WARNING."""
    config = load_config("SO2")
    from volc_alarms import SO2

    doubles.download_returns["download_SO2"] = (None, None)
    SO2.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# VAA
#
# The critical scenario replays a real recorded Volcanic Ash Advisory (a
# Sheveluch eruption advisory, 2026-09-28 17:53 UTC) through the real detection
# path offline: the download_mesonet_vaa_list double returns the advisory's
# text_link, and fetch_vaa_page is faked to serve the recorded advisory text, so
# the real process_vaa_id (parse_vaa_fields, text_to_latlon, parse_vaa_dtg) +
# find_nearest_volcano + create_message all run. make_map is stubbed -- the
# figure render is covered by the pre-existing test_figure.py.
# ---------------------------------------------------------------------------
VAA_T0 = UTCDateTime("2026-09-28T18:00:00")  # ~7 min after the recorded advisory
VAA_TEXT_FIXTURE = FIXTURE_DATA_DIR / "vaa_Sheveluch_20260928T1753.txt"
VAA_EVENT_ID = "20260928/1753Z-SHEVELUCH"


def _vaa_link_df():
    """The one-row text_link DataFrame download_mesonet_vaa_list returns."""
    return pd.DataFrame({"text_link": ["https://example.test/nwstext/202609281753"]})


def _install_vaa_page(doubles):
    """Fake fetch_vaa_page to serve the recorded advisory text (real parse runs)."""
    from volc_alarms.alarms.VAA import detection as vaa_detection

    text = VAA_TEXT_FIXTURE.read_text(encoding="utf-8")

    class _Resp:
        def __init__(self, t):
            self.text = t

    doubles.monkeypatch.setattr(vaa_detection, "fetch_vaa_page", lambda url, **k: _Resp(text))


def vaa_critical(doubles, load_config):
    """Recorded Sheveluch VAA -> CRITICAL detection + full send.

    download_mesonet_vaa_list returns the advisory's text_link and fetch_vaa_page
    serves the recorded advisory text, so run_alarm runs the real process_vaa_id
    parse + find_nearest_volcano + create_message and the full send sequence.
    make_map is stubbed (render covered by test_figure.py).
    """
    _clean_test_db()
    config = load_config("VAA")
    from volc_alarms import VAA

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_mesonet_vaa_list"] = _vaa_link_df()
    _install_vaa_page(doubles)
    doubles.patch_figure_builder(VAA, "make_map")
    VAA.run_alarm(config, VAA_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def vaa_webpage_error(doubles, load_config):
    """download_mesonet_vaa_list returns None -> webpage error WARNING."""
    config = load_config("VAA")
    from volc_alarms import VAA

    doubles.download_returns["download_mesonet_vaa_list"] = None
    VAA.run_alarm(config, VAA_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def vaa_no_advisories(doubles, load_config):
    """Empty advisory list -> OK 'No new Volcanic Ash Advisories'."""
    config = load_config("VAA")
    from volc_alarms import VAA

    doubles.download_returns["download_mesonet_vaa_list"] = pd.DataFrame({"text_link": []})
    VAA.run_alarm(config, VAA_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def vaa_already_processed(doubles, load_config):
    """The recorded VAA, but already in the DB -> OK 'No Volcanic Ash Advisories.'"""
    _clean_test_db()
    config = load_config("VAA")
    from volc_alarms import VAA
    from volc_alarms.utils import alarming

    conn = alarming.get_conn(test=False)
    try:
        table = alarming.resolve_table_name(test=False)
        conn.execute(
            f"INSERT INTO {table} (alarm_id, event_id, volcano, process_time, send_time) "
            f"VALUES (?, ?, ?, ?, ?)",
            (config.alarm_name, VAA_EVENT_ID, "Sheveluch",
             "2026-09-28T17:53:00Z", "2026-09-28T18:00:00Z"),
        )
    finally:
        conn.close()

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.download_returns["download_mesonet_vaa_list"] = _vaa_link_df()
    _install_vaa_page(doubles)
    doubles.patch_figure_builder(VAA, "make_map")
    VAA.run_alarm(config, VAA_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Magnitude
#
# The critical scenario replays a real M3.25 event near Denison (2026-01-04
# 20:16:41 UTC) through the real detection + message path from two recorded
# fixtures -- the FDSN hypocenters CSV row and the per-event QuakeML -- with the
# figure builder stubbed (the full plot_event render is unit-tested separately in
# tests/alarms/Magnitude/test_figure.py, which owns the waveform + StationXML
# fixtures). The other scenarios drive the remaining run_alarm branches with
# small crafted inputs / seeded DB state.
# ---------------------------------------------------------------------------
MAGNITUDE_EVENT_T0 = UTCDateTime("2026-01-04T20:30:00")  # ~13 min after the event
MAGNITUDE_CSV_FIXTURE = FIXTURE_DATA_DIR / "magnitude_Denison_20260104T2016.csv"
MAGNITUDE_QUAKEML_FIXTURE = FIXTURE_DATA_DIR / "magnitude_Denison_20260104T2016.quakeml"
MAGNITUDE_EVENT_ID = "93980456"


def _load_magnitude_csv():
    """Load the recorded FDSN hypocenters CSV as download_hypocenters_csv returns it."""
    csv_df = pd.read_csv(MAGNITUDE_CSV_FIXTURE).rename(columns={"id": "event_id"})
    csv_df["time"] = pd.to_datetime(csv_df["time"])
    return csv_df


def magnitude_representative(doubles, load_config):
    """Default empty FDSN catalog -> 'No new earthquakes' OK."""
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    Magnitude.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def magnitude_critical(doubles, load_config):
    """Recorded M3.25 Denison event -> CRITICAL detection + full send.

    Feeds the recorded CSV + QuakeML to the faked downloaders and stubs the figure
    builder (plot_event), so run_alarm runs the real detection + message path:
    find_nearest_volcano places the event ~4.7 km from Denison (< the 10 km config
    distance) -> CRITICAL, create_message renders the alert from the real picks,
    and the full Mattermost -> DB record -> cleanup -> Icinga sequence fires. The
    render itself is covered by test_figure.py.
    """
    _clean_test_db()
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    doubles.hypocenter_csv = _load_magnitude_csv()
    doubles.hypocenter_xml = read_events(str(MAGNITUDE_QUAKEML_FIXTURE))
    doubles.patch_figure_builder(Magnitude.detection, "plot_event")

    Magnitude.run_alarm(config, MAGNITUDE_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def magnitude_fdsn_error(doubles, load_config):
    """download_hypocenters_csv returns None (FDSN failure) -> WARNING."""
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    doubles.hypocenter_csv_error = True  # CSV double returns None (error branch)
    Magnitude.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def magnitude_not_near_volcano(doubles, load_config):
    """A real-magnitude quake far from any volcano -> OK 'No new earthquakes'.

    The event clears magmin/maxdep so it appears in the catalog, but sits in the
    Gulf of Alaska > the 10 km config distance from every volcano, so the
    distance filter drops it before any detection.
    """
    _clean_test_db()
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    doubles.hypocenter_csv = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-01-04 20:00:00"]),
            "latitude": [56.0],
            "longitude": [-150.0],   # open Gulf of Alaska, far from any volcano
            "depth": [10.0],
            "mag": [3.5],
            "event_id": ["ak_offshore_test"],
        }
    )
    Magnitude.run_alarm(config, MAGNITUDE_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def magnitude_already_processed(doubles, load_config):
    """The recorded event, but already in the DB -> OK 'Old event detected'.

    Seeds the event id into the alarm-history DB via the real record_send, so
    run_alarm's already_processed() check (a real sqlite read) short-circuits the
    per-event loop to the 'Old event detected' OK branch without re-sending.
    """
    _clean_test_db()
    config = load_config("Magnitude")
    from volc_alarms import Magnitude
    from volc_alarms.utils import alarming

    # Pre-record this event id under the Magnitude alarm_id directly in the sqlite
    # DB that already_processed() reads. run_alarm runs with test_flag=False, so it
    # queries the non-test 'sent_events' table; seed there. (alarming.record_send
    # is doubled to an in-memory store by install(), so we write via get_conn to
    # reach the real file already_processed uses.)
    conn = alarming.get_conn(test=False)
    try:
        table = alarming.resolve_table_name(test=False)
        conn.execute(
            f"INSERT INTO {table} (alarm_id, event_id, volcano, process_time, send_time) "
            f"VALUES (?, ?, ?, ?, ?)",
            (config.alarm_name, MAGNITUDE_EVENT_ID, "Denison",
             "2026-01-04T20:16:41Z", "2026-01-04T20:30:00Z"),
        )
    finally:
        conn.close()

    doubles.hypocenter_csv = _load_magnitude_csv()
    doubles.hypocenter_xml = read_events(str(MAGNITUDE_QUAKEML_FIXTURE))
    doubles.patch_figure_builder(Magnitude.detection, "plot_event")

    Magnitude.run_alarm(config, MAGNITUDE_EVENT_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Swarm
#
# Swarm clusters an FDSN earthquake catalog (DBSCAN in space+time, two parameter
# sets) and branches on whether new events form a swarm, continue a prior swarm
# (from the swarm_table DB), or neither. Scenarios feed a recorded/crafted CSV to
# the download_hypocenters_csv double (as the real downloader returns it, id ->
# event_id) so the real get_swarms / compare_swarms / check_swarm_continue run;
# make_figure is stubbed. VOLCANO_LIST is pinned to the avo list for determinism.
#
# Fixtures:
#   - swarm_Makushin_20260923.csv        real Makushin swarm (long-param CRITICAL)
#   - swarm_multi_param_synthetic.csv    one sequence caught by BOTH params
#   - swarm_simultaneous_synthetic.csv   two clusters at different volcanoes
# ---------------------------------------------------------------------------
SWARM_T0 = UTCDateTime("2026-09-23T21:30:00")  # just after the recorded Makushin swarm
SWARM_MAKUSHIN_CSV = FIXTURE_DATA_DIR / "swarm_Makushin_20260923.csv"
SWARM_MULTI_PARAM_CSV = FIXTURE_DATA_DIR / "swarm_multi_param_synthetic.csv"
SWARM_SIMULTANEOUS_CSV = FIXTURE_DATA_DIR / "swarm_simultaneous_synthetic.csv"


def _load_swarm_csv(path):
    """Load a swarm CSV as download_hypocenters_csv returns it (id -> event_id)."""
    return _load_swarm_csv_from_df(pd.read_csv(path))


def _load_swarm_csv_from_df(df):
    """Shape a crafted df exactly like download_hypocenters_csv does.

    The real downloader round-trips each time through UTCDateTime(...).strftime()
    then pd.to_datetime, yielding tz-NAIVE timestamps, and renames id -> event_id.
    Matching that (rather than a plain tz-aware pd.to_datetime) keeps the
    get_swarms time comparison (Series > naive-string) valid.
    """
    df = df.rename(columns={"id": "event_id"})
    df["time"] = df["time"].apply(lambda t: UTCDateTime(t).strftime("%Y-%m-%d %H:%M:%S.%f"))
    df["time"] = pd.to_datetime(df["time"])
    return df


def _seed_swarm_events(config, events):
    """Seed prior swarm events into the real swarm_table via record_swarm_event_ids.

    ``events`` is a DataFrame with event_id/time/latitude/longitude/depth/mag/
    v_name columns (the schema record_swarm_event_ids writes).
    """
    from volc_alarms.utils import alarming

    alarming.record_swarm_event_ids(events, test=False)


def swarm_critical(doubles, load_config):
    """Recorded Makushin swarm -> CRITICAL detection + full send.

    The real Makushin catalog clusters (via the 24h 'long' params) into one
    swarm, so run_alarm reaches CRITICAL and the full figure -> Mattermost ->
    DB record -> Icinga sequence. make_figure is stubbed (render in test_figure.py).
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.hypocenter_csv = _load_swarm_csv(SWARM_MAKUSHIN_CSV)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_multi_param(doubles, load_config):
    """One sequence caught by BOTH parameter sets -> a single deduped CRITICAL.

    The synthetic burst satisfies the short (>=6 in 1h) params and, with a
    trailing trickle, also the long (>=12 in 24h) params. get_swarms returns a
    detection from each, and compare_swarms collapses the overlapping pair to the
    single shorter-duration swarm -> one CRITICAL send.
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.hypocenter_csv = _load_swarm_csv(SWARM_MULTI_PARAM_CSV)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_simultaneous_swarms(doubles, load_config):
    """Two clusters at different volcanoes -> two CRITICAL sends.

    Synthetic events form two spatially separate swarms (near Spurr and Redoubt),
    each satisfying the short params. compare_swarms keeps both (disjoint event
    sets), so run_alarm sends one CRITICAL per swarm. Exercises the previously
    untested multi-swarm path (compare_swarms merges on event_id/time).
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    doubles.hypocenter_csv = _load_swarm_csv(SWARM_SIMULTANEOUS_CSV)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_continuation(doubles, load_config):
    """New events extend a prior swarm (from the DB) -> WARNING, not a new swarm.

    Seeds a near-complete prior swarm into swarm_table, then feeds a couple of new
    events that (alone) don't form a swarm but, merged with the seeded events via
    check_swarm_continue, extend the existing cluster -> the 'Ongoing swarm
    activity' WARNING branch (no CRITICAL send).
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))

    # Seed 11 prior events tightly clustered near Spurr over the last ~2 h.
    spurr_lat, spurr_lon = 61.2989, -152.2539
    seed_times = [pd.Timestamp("2026-09-23 19:30:00", tz="UTC") + pd.Timedelta(minutes=6 * i)
                  for i in range(11)]
    seeded = pd.DataFrame(
        {
            "event_id": [f"cont_seed_{i}" for i in range(11)],
            "time": seed_times,
            "latitude": [spurr_lat + 0.002 * (i % 3) for i in range(11)],
            "longitude": [spurr_lon + 0.002 * (i % 2) for i in range(11)],
            "depth": [4.0] * 11,
            "mag": [0.5] * 11,
            "v_name": ["Spurr"] * 11,
        }
    )
    _seed_swarm_events(config, seeded)

    # Two NEW events extending the cluster (too few to be a swarm on their own).
    new_times = [pd.Timestamp("2026-09-23 21:10:00") + pd.Timedelta(minutes=8 * i) for i in range(2)]
    new_df = pd.DataFrame(
        {
            "time": [t.strftime("%Y-%m-%dT%H:%M:%S.000Z") for t in new_times],
            "latitude": [spurr_lat + 0.001, spurr_lat + 0.002],
            "longitude": [spurr_lon + 0.001, spurr_lon - 0.001],
            "depth": [4.0, 4.5],
            "mag": [0.6, 0.7],
            "id": ["cont_new_0", "cont_new_1"],
        }
    )
    doubles.hypocenter_csv = _load_swarm_csv_from_df(new_df)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_no_swarm(doubles, load_config):
    """Events near a volcano but too few/scattered to cluster -> OK.

    Three events near Spurr, below the min_num_evt threshold, so get_swarms finds
    no cluster and there is no prior swarm to continue -> 'No new swarm activity'.
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    spurr_lat, spurr_lon = 61.2989, -152.2539
    times = [pd.Timestamp("2026-09-23 21:00:00") + pd.Timedelta(minutes=10 * i) for i in range(3)]
    df = pd.DataFrame(
        {
            "time": [t.strftime("%Y-%m-%dT%H:%M:%S.000Z") for t in times],
            "latitude": [spurr_lat, spurr_lat + 0.001, spurr_lat - 0.001],
            "longitude": [spurr_lon, spurr_lon + 0.001, spurr_lon - 0.001],
            "depth": [4.0, 4.2, 4.1],
            "mag": [0.5, 0.6, 0.4],
            "id": ["ns0", "ns1", "ns2"],
        }
    )
    doubles.hypocenter_csv = _load_swarm_csv_from_df(df)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_not_near_volcano(doubles, load_config):
    """Events far from any volcano -> OK 'No new swarm activity'.

    A cluster in the open Gulf of Alaska, beyond volcano_distance from every
    volcano, so the distance filter drops them all before clustering.
    """
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.monkeypatch.setenv("VOLCANO_LIST", str(LIGHTNING_VOLCANO_LIST))
    times = [pd.Timestamp("2026-09-23 21:00:00") + pd.Timedelta(minutes=5 * i) for i in range(8)]
    df = pd.DataFrame(
        {
            "time": [t.strftime("%Y-%m-%dT%H:%M:%S.000Z") for t in times],
            "latitude": [56.0 + 0.001 * i for i in range(8)],
            "longitude": [-150.0 + 0.001 * i for i in range(8)],  # open ocean
            "depth": [10.0] * 8,
            "mag": [1.0] * 8,
            "id": [f"far{i}" for i in range(8)],
        }
    )
    doubles.hypocenter_csv = _load_swarm_csv_from_df(df)
    doubles.patch_figure_builder(Swarm, "make_figure")
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


def swarm_fdsn_error(doubles, load_config):
    """download_hypocenters_csv returns None -> FDSN connection error WARNING."""
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    doubles.hypocenter_csv_error = True
    Swarm.run_alarm(config, SWARM_T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Maps frozen-baseline name -> (alarm module, scenario driver). The test
# parametrizes over the keys; the module names the baselines/<Module>/ subdir the
# frozen JSON lives in. Keys use "-" as the module/variant boundary so they split
# unambiguously even though several module names and variants contain "_"
# (e.g. "NOAA_CIMSS-representative", "Infrasound-not_enough_channels").
SCENARIOS = {
    "RSAM-critical": ("RSAM", rsam_critical),
    "RSAM-elevated": ("RSAM", rsam_elevated),
    "RSAM-arrested": ("RSAM", rsam_arrested),
    "RSAM-normal": ("RSAM", rsam_normal),
    "RSAM-data_missing": ("RSAM", rsam_data_missing),
    "Infrasound-not_enough_channels": ("Infrasound", infrasound_not_enough_channels),
    "Infrasound-below_amplitude": ("Infrasound", infrasound_below_amplitude),
    "Infrasound-wrong_backazimuth": ("Infrasound", infrasound_wrong_backazimuth),
    "Infrasound-critical": ("Infrasound", infrasound_critical),
    "Tremor-data_missing": ("Tremor", tremor_data_missing),
    "Tremor-normal": ("Tremor", tremor_normal),
    "Tremor-elevated": ("Tremor", tremor_elevated),
    "Tremor-elevated_no_new_events": ("Tremor", tremor_elevated_no_new_events),
    "Tremor-low_amplitude": ("Tremor", tremor_low_amplitude),
    "Tremor-missing_rsam_station": ("Tremor", tremor_missing_rsam_station),
    "Tremor-critical": ("Tremor", tremor_critical),
    "Lightning-critical": ("Lightning", lightning_critical),
    "Lightning-distal": ("Lightning", lightning_distal),
    "Lightning-ignored_volcano": ("Lightning", lightning_ignored_volcano),
    "Lightning-no_data": ("Lightning", lightning_no_data),
    "Lightning-api_error": ("Lightning", lightning_api_error),
    "Lightning-all_seen": ("Lightning", lightning_all_seen),
    "NOAA_CIMSS-critical": ("NOAA_CIMSS", noaa_cimss_critical),
    "NOAA_CIMSS-api_error": ("NOAA_CIMSS", noaa_cimss_api_error),
    "NOAA_CIMSS-no_new_alerts": ("NOAA_CIMSS", noaa_cimss_no_new_alerts),
    "NOAA_CIMSS-webpage_error": ("NOAA_CIMSS", noaa_cimss_webpage_error),
    "NOAA_CIMSS-already_processed": ("NOAA_CIMSS", noaa_cimss_already_processed),
    "NOAA_CIMSS-ignored_volcano": ("NOAA_CIMSS", noaa_cimss_ignored_volcano),
    "Pilot_Report-critical": ("Pilot_Report", pilot_report_critical),
    "Pilot_Report-non_urgent": ("Pilot_Report", pilot_report_non_urgent),
    "Pilot_Report-api_error": ("Pilot_Report", pilot_report_api_error),
    "Pilot_Report-no_reports": ("Pilot_Report", pilot_report_no_reports),
    "Pilot_Report-already_processed": ("Pilot_Report", pilot_report_already_processed),
    "SO2-representative": ("SO2", so2_representative),
    "VAA-critical": ("VAA", vaa_critical),
    "VAA-webpage_error": ("VAA", vaa_webpage_error),
    "VAA-no_advisories": ("VAA", vaa_no_advisories),
    "VAA-already_processed": ("VAA", vaa_already_processed),
    "Magnitude-representative": ("Magnitude", magnitude_representative),
    "Magnitude-critical": ("Magnitude", magnitude_critical),
    "Magnitude-fdsn_error": ("Magnitude", magnitude_fdsn_error),
    "Magnitude-not_near_volcano": ("Magnitude", magnitude_not_near_volcano),
    "Magnitude-already_processed": ("Magnitude", magnitude_already_processed),
    "Swarm-critical": ("Swarm", swarm_critical),
    "Swarm-multi_param": ("Swarm", swarm_multi_param),
    "Swarm-simultaneous_swarms": ("Swarm", swarm_simultaneous_swarms),
    "Swarm-continuation": ("Swarm", swarm_continuation),
    "Swarm-no_swarm": ("Swarm", swarm_no_swarm),
    "Swarm-not_near_volcano": ("Swarm", swarm_not_near_volcano),
    "Swarm-fdsn_error": ("Swarm", swarm_fdsn_error),
}
