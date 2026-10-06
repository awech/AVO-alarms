"""Unit tests for ``volc_alarms.alarms.RSAM.detection``.

``RSAM_to_DR`` converts a trace's RMS (counts) to reduced displacement using the
station response from the in-repo test station XML and the station->volcano
distance from the bundled volcano list. No network is used.

Covered:
* RSAM_to_DR — positive, finite reduced displacement that scales with amplitude
"""

from __future__ import annotations

import numpy as np
import pytest
from obspy import Trace, UTCDateTime

from volc_alarms.alarms.RSAM.detection import RSAM_to_DR

pytestmark = pytest.mark.unit


def _trace(amplitude, station="CEAP"):
    """A sinusoidal AV trace for a station present in the test station XML."""
    data = amplitude * np.sin(np.linspace(0, 20 * np.pi, 6000))
    tr = Trace(data=data.astype("float64"))
    tr.stats.network = "AV"
    tr.stats.station = station
    tr.stats.location = ""
    tr.stats.channel = "BHZ"
    tr.stats.sampling_rate = 100.0
    tr.stats.starttime = UTCDateTime("2025-01-01T00:00:00")
    return tr


def test_rsam_to_dr_returns_positive_finite_value():
    """RSAM_to_DR returns a positive, finite reduced displacement for a real station."""
    dr = RSAM_to_DR(_trace(1000.0), "Cleveland")
    assert np.isfinite(dr)
    assert dr > 0


def test_rsam_to_dr_scales_with_signal_amplitude():
    """RSAM_to_DR grows monotonically with trace RMS amplitude (linear scaling)."""
    dr_low = RSAM_to_DR(_trace(500.0), "Cleveland")
    dr_high = RSAM_to_DR(_trace(5000.0), "Cleveland")
    assert dr_high > dr_low
    # RMS scales linearly with amplitude, so a 10x amplitude gives ~10x DR.
    assert dr_high / dr_low == pytest.approx(10.0, rel=1e-6)
