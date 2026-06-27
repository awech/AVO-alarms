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
3. Run: REGEN_BASELINES=1 pytest tests/alarms/test_baselines.py -k "your_scenario"
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Stream, Trace, UTCDateTime
from obspy.core.event import Catalog, Event, Magnitude as EventMagnitude, Origin, ResourceIdentifier

from tests.alarms.snapshot_utils import T0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
# ---------------------------------------------------------------------------
def infrasound_representative(doubles, load_config):
    """Default zero-filled waveforms -> 'Not enough channels!' WARNING."""
    config = load_config("Infrasound")
    from volc_alarms import Infrasound

    doubles.patch_figure_builder(Infrasound, "make_figure")
    Infrasound.run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True)


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
    "Infrasound_representative": infrasound_representative,
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
