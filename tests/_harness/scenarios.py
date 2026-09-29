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
2. Register it in the SCENARIOS dict at the bottom of this file
3. Run: REGEN_BASELINES=1 pytest -m integration -k "your_scenario"
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Stream, Trace, UTCDateTime
from obspy.core.event import Catalog, Event, Magnitude as EventMagnitude, Origin, ResourceIdentifier

from obspy import read as read_stream

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
# ---------------------------------------------------------------------------
def lightning_representative(doubles, load_config):
    """Default download returns None -> Volcview-API error WARNING."""
    config = load_config("Lightning")
    from volc_alarms import Lightning

    doubles.download_returns["download_lightning"] = None
    Lightning.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def lightning_critical(doubles, load_config):
    """Recorded proximal strokes -> CRITICAL send with event-id list record."""
    config = load_config("Lightning")
    from volc_alarms import Lightning

    # Two proximal strokes near a single volcano within the look-back window.
    strokes = pd.DataFrame(
        {
            "id": ["L1", "L2"],
            "time": pd.to_datetime(["2024-12-31 23:30:00", "2024-12-31 23:40:00"]),
            "api_vdist": [5.0, 8.0],
            "api_vname": ["Pavlof", "Pavlof"],
            "api_vlat": [55.420, 55.420],
            "api_vlon": [-161.887, -161.887],
            "latitude": [55.40, 55.41],
            "longitude": [-161.85, -161.86],
            "dataSource": ["EN", "EN"],
        }
    )
    doubles.download_returns["download_lightning"] = strokes
    # test_flag=True takes the api_vdist/api_vname branch (no volcano-list lookup).
    doubles.patch_figure_builder(Lightning, "plot_fig")
    Lightning.run_alarm(config, T0, test_flag=True, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# NOAA_CIMSS
# ---------------------------------------------------------------------------
def noaa_cimss_representative(doubles, load_config):
    """Default download returns None -> Volcview-API error WARNING."""
    config = load_config("NOAA_CIMSS")
    from volc_alarms import NOAA_CIMSS

    doubles.download_returns["download_cimss_vv_api"] = None
    NOAA_CIMSS.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Pilot_Report
# ---------------------------------------------------------------------------
def pilot_report_representative(doubles, load_config):
    """Default download returns ('OK', None) -> 'No new pilot reports' OK."""
    config = load_config("PIREP")
    from volc_alarms import Pilot_Report

    doubles.download_returns["download_pilot_reports"] = ("OK", None)
    Pilot_Report.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


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
# ---------------------------------------------------------------------------
def vaa_representative(doubles, load_config):
    """Default download returns None -> webpage error WARNING."""
    config = load_config("VAA")
    from volc_alarms import VAA

    doubles.download_returns["download_mesonet_vaa_list"] = None
    VAA.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Magnitude
# ---------------------------------------------------------------------------
def magnitude_representative(doubles, load_config):
    """Default empty FDSN catalog -> 'No new earthquakes' OK."""
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    Magnitude.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def magnitude_critical(doubles, load_config):
    """Crafted event near Pavlof -> CRITICAL detection + send sequence."""
    _clean_test_db()
    config = load_config("Magnitude")
    from volc_alarms import Magnitude

    # Hypocenter CSV (download_hypocenters_csv return): one event at Pavlof.
    doubles.hypocenter_csv = pd.DataFrame(
        {
            "time": ["2024-12-31 23:55:00"],
            "latitude": [55.4173],
            "longitude": [-161.8937],
            "depth": [5.0],
            "mag": [3.2],
            "event_id": ["ak0258testevt"],
        }
    )

    # Hypocenter XML (download_hypocenter_xml return): a minimal Catalog.
    origin = Origin(
        latitude=55.4173,
        longitude=-161.8937,
        depth=5000.0,
        time=UTCDateTime("2024-12-31T23:55:00"),
        evaluation_mode="manual",
    )
    mag = EventMagnitude(mag=3.2)
    event = Event(
        resource_id=ResourceIdentifier(id="smi:local/event/ak0258testevt"),
        origins=[origin],
        magnitudes=[mag],
    )
    event.preferred_origin_id = origin.resource_id
    event.preferred_magnitude_id = mag.resource_id
    doubles.hypocenter_xml = Catalog(events=[event])

    # Avoid matplotlib by replacing the figure builder used in process_event.
    doubles.patch_figure_builder(Magnitude.detection, "plot_event")

    Magnitude.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Swarm
# ---------------------------------------------------------------------------
def swarm_representative(doubles, load_config):
    """Default empty FDSN catalog -> 'No new swarm activity' OK."""
    _clean_test_db()
    config = load_config("Swarm")
    from volc_alarms import Swarm

    Swarm.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Maps frozen-baseline name -> scenario driver. The test parametrizes over this.
SCENARIOS = {
    "RSAM_critical": rsam_critical,
    "RSAM_elevated": rsam_elevated,
    "RSAM_arrested": rsam_arrested,
    "RSAM_normal": rsam_normal,
    "RSAM_data_missing": rsam_data_missing,
    "Infrasound_not_enough_channels": infrasound_not_enough_channels,
    "Infrasound_below_amplitude": infrasound_below_amplitude,
    "Infrasound_wrong_backazimuth": infrasound_wrong_backazimuth,
    "Infrasound_critical": infrasound_critical,
    "Tremor_data_missing": tremor_data_missing,
    "Tremor_normal": tremor_normal,
    "Tremor_elevated": tremor_elevated,
    "Tremor_elevated_no_new_events": tremor_elevated_no_new_events,
    "Tremor_low_amplitude": tremor_low_amplitude,
    "Tremor_missing_rsam_station": tremor_missing_rsam_station,
    "Tremor_critical": tremor_critical,
    "Lightning_representative": lightning_representative,
    "Lightning_critical": lightning_critical,
    "NOAA_CIMSS_representative": noaa_cimss_representative,
    "Pilot_Report_representative": pilot_report_representative,
    "SO2_representative": so2_representative,
    "VAA_representative": vaa_representative,
    "Magnitude_representative": magnitude_representative,
    "Magnitude_critical": magnitude_critical,
    "Swarm_representative": swarm_representative,
}
