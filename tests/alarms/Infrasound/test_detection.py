"""Unit tests for ``volc_alarms.alarms.Infrasound.detection``.

These cover the back-azimuth computation and the LTS result-filtering logic with
crafted Streams / DataFrames. No LTS array processing is run (``do_LTS`` calls
the ``lts_array`` solver and ``get_pressures`` needs real windows; both are
covered via the integration path).

Covered:
* get_target_backazimuth — fills each target's back_azimuth from array centroid
* filter_lts_results      — keeps only rows passing MCCM/pressure/velocity/azimuth
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace, UTCDateTime

from volc_alarms.alarms.Infrasound.detection import (
    filter_lts_results,
    get_target_backazimuth,
)

pytestmark = pytest.mark.unit


def _trace_with_coords(sta, lat, lon):
    tr = Trace(data=np.zeros(100, dtype="float64"))
    tr.stats.network = "AV"
    tr.stats.station = sta
    tr.stats.channel = "BDF"
    tr.stats.sampling_rate = 100.0
    tr.stats.starttime = UTCDateTime("2025-01-01T00:00:00")
    tr.stats.coordinates = SimpleNamespace(latitude=lat, longitude=lon, elevation=0.0)
    return tr


# ---------------------------------------------------------------------------
# get_target_backazimuth
# ---------------------------------------------------------------------------
def test_get_target_backazimuth_fills_missing_back_azimuth():
    """get_target_backazimuth computes back_azimuth from the array centroid to each target."""
    st = Stream([
        _trace_with_coords("A", 55.0, -162.0),
        _trace_with_coords("B", 55.02, -162.0),
    ])
    # Target due north of the ~55.01 centroid: gps2dist_azimuth returns the
    # forward azimuth from the centroid to the target, which is ~0 (north).
    config = SimpleNamespace(targets=[{"lat": 56.0, "lon": -162.0}])

    out = get_target_backazimuth(st, config)
    baz = out.targets[0]["back_azimuth"]
    assert baz == pytest.approx(0.0, abs=1.0)


def test_get_target_backazimuth_preserves_existing_value():
    """get_target_backazimuth leaves a target's back_azimuth alone when already set."""
    st = Stream([_trace_with_coords("A", 55.0, -162.0)])
    config = SimpleNamespace(targets=[{"lat": 56.0, "lon": -162.0, "back_azimuth": 42.0}])

    out = get_target_backazimuth(st, config)
    assert out.targets[0]["back_azimuth"] == 42.0


# ---------------------------------------------------------------------------
# filter_lts_results
# ---------------------------------------------------------------------------
def test_filter_lts_results_keeps_only_rows_within_all_thresholds():
    """filter_lts_results retains rows passing MCCM, pressure, velocity, and azimuth gates."""
    df = pd.DataFrame(
        {
            # row 0 passes everything; rows 1-4 each fail one gate.
            "MCCM": [0.9, 0.1, 0.9, 0.9, 0.9],
            "Pressure": [5.0, 5.0, 0.1, 5.0, 5.0],
            "Velocity": [340.0, 340.0, 340.0, 100.0, 340.0],  # m/s (/1000 -> km/s)
            "Azimuth": [180.0, 180.0, 180.0, 180.0, 10.0],
        }
    )
    target = {
        "cmin": 0.5,
        "min_pa": 1.0,
        "vmin": 0.28,
        "vmax": 0.45,
        "back_azimuth": 180.0,
        "az_tolerance": 15.0,
    }

    out = filter_lts_results(df, target)

    assert len(out) == 1
    assert out.index.tolist() == [0]
