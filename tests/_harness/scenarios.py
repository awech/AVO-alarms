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
# ---------------------------------------------------------------------------
def rsam_representative(doubles, load_config):
    """Default zero-filled waveforms -> 'RSAM data missing!' WARNING."""
    config = load_config("RSAM")
    from volc_alarms import RSAM

    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


def rsam_critical(doubles, load_config):
    """Crafted waveforms (3 source stations hot, arrestor quiet) -> CRITICAL send."""
    config = load_config("RSAM")
    from volc_alarms import RSAM

    hot = {"CEAP", "CERA", "CETU"}  # exceed their levels -> detection
    arrestor = "AMKA"  # must stay below its level

    def _factory(nslc_list, T1, T2, **_):
        sr = 100.0
        npts = max(int(round((T2 - T1) * sr)), 1)
        t = np.arange(npts) / sr
        st = Stream()
        for nslc in nslc_list:
            sta = nslc.split(".")[1]
            if sta in hot:
                data = 3000.0 * np.sin(2 * np.pi * 2.0 * t)
            elif sta == arrestor:
                data = 5.0 * np.sin(2 * np.pi * 2.0 * t)
            else:
                data = np.zeros(npts)
            st += _make_trace(nslc, T1, data, sampling_rate=sr)
        return st

    doubles.waveform_factory = _factory
    # Avoid matplotlib / the second waveform download in make_figure.
    doubles.patch_figure_builder(RSAM, "make_figure")
    RSAM.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


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
# ---------------------------------------------------------------------------
def tremor_representative(doubles, load_config):
    """Empty tremor DB + zero-filled waveforms -> 'Data missing!' WARNING."""
    _clean_test_db()
    config = load_config("Tremor")
    from volc_alarms import Tremor

    Tremor.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


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
    "RSAM_representative": rsam_representative,
    "RSAM_critical": rsam_critical,
    "Infrasound_not_enough_channels": infrasound_not_enough_channels,
    "Infrasound_below_amplitude": infrasound_below_amplitude,
    "Infrasound_wrong_backazimuth": infrasound_wrong_backazimuth,
    "Infrasound_critical": infrasound_critical,
    "Tremor_representative": tremor_representative,
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
