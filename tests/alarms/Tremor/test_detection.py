"""Unit tests for ``volc_alarms.alarms.Tremor.detection``.

These cover the grid reconstruction, QC, envelope, and Icinga-text helpers with
crafted configs / obspy Streams. No network or enveloc location run is involved
(``run_enveloc`` needs the enveloc solver + travel-time grid and is covered via
the integration path).

Covered:
* build_grid          — reconstruct lon/lat/depth arrays from scalar bounds
* qc_checks           — drop gappy traces and count unique station latitudes
* make_env            — envelope + downsample to a 5 Hz, taper-trimmed stream
* create_icinga_test  — duration/recency text for detection and quiet cases
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace, UTCDateTime

from volc_alarms.alarms.Tremor.detection import (
    build_grid,
    create_icinga_test,
    make_env,
    qc_checks,
)

pytestmark = pytest.mark.unit


def _trace(sta, t0, npts=3000, sr=50.0, value=1.0, lat=55.0):
    tr = Trace(data=np.full(npts, value, dtype="float64"))
    tr.stats.network = "AV"
    tr.stats.station = sta
    tr.stats.location = ""
    tr.stats.channel = "BHZ"
    tr.stats.sampling_rate = sr
    tr.stats.starttime = t0
    tr.stats.coordinates = {"latitude": lat, "longitude": -161.9, "elevation": 0.0}
    return tr


# ---------------------------------------------------------------------------
# build_grid
# ---------------------------------------------------------------------------
def test_build_grid_reconstructs_arrays_from_bounds():
    """build_grid builds inclusive lon/lat/depth arrays from the scalar bounds/steps."""
    config = SimpleNamespace(
        grid={
            "lon_min": -162.0, "lon_max": -161.0, "lon_step": 0.5,
            "lat_min": 55.0, "lat_max": 56.0, "lat_step": 0.5,
            "depth_min": 0.0, "depth_max": 10.0, "depth_step": 5.0,
        }
    )
    grid = build_grid(config)
    np.testing.assert_allclose(grid["lons"], [-162.0, -161.5, -161.0])
    np.testing.assert_allclose(grid["lats"], [55.0, 55.5, 56.0])
    np.testing.assert_allclose(grid["deps"], [0.0, 5.0, 10.0])


# ---------------------------------------------------------------------------
# qc_checks
# ---------------------------------------------------------------------------
def test_qc_checks_drops_gappy_traces_and_counts_unique_latitudes():
    """qc_checks removes >3% zero-filled traces and returns the unique-latitude count."""
    t0 = UTCDateTime("2025-01-01T00:00:00")
    good1 = _trace("AAA", t0, value=1.0, lat=55.0)
    good2 = _trace("BBB", t0, value=1.0, lat=56.0)
    gappy = _trace("CCC", t0, value=0.0, lat=57.0)  # all zeros -> dropped
    st = Stream([good1, good2, gappy])

    n_unique_lats = qc_checks(st)

    assert len(st) == 2                 # gappy trace removed in place
    assert n_unique_lats == 2           # two distinct latitudes remain


# ---------------------------------------------------------------------------
# make_env
# ---------------------------------------------------------------------------
def test_make_env_downsamples_to_5hz_envelope():
    """make_env returns a positive-valued envelope stream resampled to 5 Hz."""
    t0 = UTCDateTime("2025-01-01T00:00:00")
    tr = _trace("AAA", t0, npts=3000, sr=50.0, value=1.0)
    tr.data = np.sin(np.linspace(0, 40 * np.pi, tr.stats.npts))
    st = Stream([tr])
    config = SimpleNamespace(taper=2.0, lowpass=0.5)

    env = make_env(st, config, t0, t0 + 60)

    assert env[0].stats.sampling_rate == 5.0
    # An amplitude envelope is non-negative.
    assert (env[0].data >= 0).all()


# ---------------------------------------------------------------------------
# create_icinga_test
# ---------------------------------------------------------------------------
def _icinga_config():
    return SimpleNamespace(
        lookback_window=60,
        window_length=60,
        rsam_station="AV.OKCF..BHZ",
        rsam_threshold=200,
    )


def test_create_icinga_test_reports_detection_duration_and_recency():
    """create_icinga_test summarizes detected duration + most-recent-event recency."""
    T0 = UTCDateTime("2025-01-01T01:00:00")
    cat = pd.DataFrame({"time": pd.to_datetime(["2025-01-01 00:55:00"])})
    duration_text, recency_text = create_icinga_test(cat, T0, duration=12.0, rsam=150, config=_icinga_config())

    assert "Seismicity detected in 12 of past 60 minutes." in duration_text
    assert "Most recent:" in recency_text
    assert "OKCF RSAM:150/200" in recency_text


def test_create_icinga_test_reports_no_seismicity_when_quiet():
    """create_icinga_test reports no seismicity (empty recency) when duration is zero."""
    T0 = UTCDateTime("2025-01-01T01:00:00")
    cat = pd.DataFrame({"time": pd.to_datetime([])})
    duration_text, recency_text = create_icinga_test(cat, T0, duration=0, rsam=150, config=_icinga_config())

    assert "No seismicity detected in the past 60 minutes." in duration_text
    assert "OKCF RSAM:150/200" in recency_text
