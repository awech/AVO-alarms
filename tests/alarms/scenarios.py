"""Recorded input fixtures + scenario drivers for baseline capture (task 1.2).

Each scenario configures the shared doubles (and, where an alarm needs canned
data to reach a meaningful state, the doubles' knobs / recorded fixtures), then
drives the *current* (pre-restructure) alarm's ``run_alarm`` with the fixed
``baseline_utils.T0``. The capture harness snapshots the observable behavior
afterward.

Two kinds of scenario are provided:

* **representative** -- drives each of the 10 alarms to its natural offline
  outcome with the default "no new data" doubles (an early ``OK``/``WARNING``
  Icinga heartbeat). This exercises the detection-state + Icinga-message portion
  of the Behavior_Baseline for every alarm.
* **critical / send** -- where feasible offline, recorded fixtures push an alarm
  all the way through the ``CRITICAL`` send sequence so the message subject/body,
  ``record_send`` fields and ``os.remove`` cleanup are also captured. RSAM and
  Lightning are driven this way (their detection logic is reachable with purely
  canned waveform / stroke fixtures and the existing doubles).

A scenario function takes ``(doubles, load_config)`` and returns ``None`` after
calling ``run_alarm``. ``doubles`` is the ``AlarmDoubles`` handle (it owns the
``monkeypatch`` used to patch figure builders / ``add_metadata`` for the test's
duration). ``load_config`` is the real-config loader fixture.

Alarms whose ``CRITICAL`` path cannot be reached offline without large bespoke
fixtures (live HTML scrape, FDSN QuakeML, enveloc relocation, shapefile parse)
are documented in ``baselines/README.md``; their representative baseline is
still captured here.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Stream, Trace
from obspy.core.util import AttribDict

from tests.alarms.baseline_utils import T0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _passthrough_add_metadata(doubles):
    """Patch ``processing.add_metadata`` to attach dummy coordinates offline.

    The real ``add_metadata`` reads a station XML (``STATION_XML``) and returns
    ``None`` when it is missing, which would crash the seismic alarms before they
    reach their observable Icinga heartbeat. For the representative paths the
    surviving-trace coordinates are never read (the alarms early-return on
    insufficient/gappy data), so a passthrough that simply returns the stream
    with placeholder coordinates preserves the observable outcome while keeping
    the run offline. (Documented in baselines/README.md.)
    """
    from volc_alarms.utils import processing

    def _double(st):
        for tr in st:
            tr.stats.coordinates = AttribDict(
                {"latitude": 0.0, "longitude": 0.0, "elevation": 0.0}
            )
            tr.inventory = None
        return st

    doubles.patch_callable(processing, "add_metadata", _double)


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

    def _factory(nslc_list, T1, T2, fill_value=0, iris=False, **_):
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

    _passthrough_add_metadata(doubles)
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

    _passthrough_add_metadata(doubles)
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
    "Swarm_representative": swarm_representative,
}
