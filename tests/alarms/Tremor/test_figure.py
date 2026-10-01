"""Smoke test for ``volc_alarms.alarms.Tremor.figure.make_figure``.

Tremor's ``make_figure`` is a thin wrapper over the shared spectrogram-mosaic
builder ``utils.plotting.plot_spectrogram_figure`` (the same one RSAM uses). This
confirms Tremor's wrapper runs the builder end to end without raising, faking the
one external thing (``download_waveforms`` -> synthetic 50 Hz traces) and mocking
``save_file`` to a sentinel so nothing is written to disk.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from volc_alarms.alarms.Tremor import figure as tremor_figure
from volc_alarms.utils import plotting

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2026-09-29T10:35:00")
SENTINEL_JPG = "/tmp/__sentinel_tremor_figure__.jpg"

NSLC = ["AV.HAG..BHZ", "AV.PS4A..BHZ", "AV.PVV..BHZ"]


def _trace(nslc, t1, t2, sr=50.0, freq=2.0):
    net, sta, loc, chan = nslc.split(".")
    npts = int(round((t2 - t1) * sr)) + 1
    t = np.arange(npts) / sr
    tr = Trace(data=(500.0 * np.sin(2 * np.pi * freq * t)).astype("float64"))
    tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel = net, sta, loc, chan
    tr.stats.sampling_rate = sr
    tr.stats.starttime = t1
    return tr


@pytest.fixture
def wired(monkeypatch):
    def _download(nslc_list, t1, t2):
        return Stream([_trace(nslc, t1, t2) for nslc in nslc_list])

    monkeypatch.setattr(plotting.downloading, "download_waveforms", _download)
    monkeypatch.setattr(plotting, "save_file", lambda *a, **k: SENTINEL_JPG)


def test_make_figure_runs_and_returns_path(wired):
    """Tremor.make_figure completes and returns the saved-figure path."""
    config = SimpleNamespace(alarm_name="Pavlof Tremor", plot_duration=1800, taper=5.0, f1=1.0, f2=6.0)
    result = tremor_figure.make_figure(NSLC, T0, config, test=False)
    assert result == SENTINEL_JPG
