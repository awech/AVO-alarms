"""Smoke tests for ``volc_alarms.alarms.RSAM.figure.make_figure``.

RSAM's ``make_figure`` is a thin wrapper over the shared spectrogram-mosaic
builder ``utils.plotting.plot_spectrogram_figure`` (also used by Tremor), so
this exercises that shared builder end to end. Intent is the same as the other
figure tests: confirm the builder runs without raising (figure generation is
wrapped in try/except in production and edits arrive as plotting tweaks), not
that the output looks a certain way.

The one external thing is faked: ``download_waveforms`` serves synthetic 50 Hz
traces (so the decimate/merge/spectrogram path runs), and ``save_file`` returns
a sentinel so nothing is written to disk. The real mosaic layout, per-channel
spectrogram, and axis formatting all run.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from volc_alarms.alarms.RSAM import figure as rsam_figure
from volc_alarms.utils import plotting

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2026-09-28T20:40:00")
SENTINEL_JPG = "/tmp/__sentinel_rsam_figure__.jpg"

NSLC = ["AV.PS4A..BHZ", "AV.PVV..BHZ", "AV.PS1A..BHZ"]


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
    """Fake the shared builder's download_waveforms + save_file."""

    def _download(nslc_list, t1, t2):
        return Stream([_trace(nslc, t1, t2) for nslc in nslc_list])

    # plot_spectrogram_figure resolves both names from the utils.plotting module.
    monkeypatch.setattr(plotting.downloading, "download_waveforms", _download)
    monkeypatch.setattr(plotting, "save_file", lambda *a, **k: SENTINEL_JPG)


def _config():
    return SimpleNamespace(alarm_name="Pavlof RSAM", plot_duration=1800, taper=5.0, f1=1.0, f2=5.0)


def test_make_figure_runs_and_returns_path(wired):
    """RSAM.make_figure completes and returns the saved-figure path."""
    result = rsam_figure.make_figure(NSLC, T0, _config(), test=False)
    assert result == SENTINEL_JPG


def test_make_figure_runs_with_single_channel(wired):
    """The spectrogram mosaic builder also handles a single-channel figure."""
    result = rsam_figure.make_figure(["AV.PS4A..BHZ"], T0, _config(), test=False)
    assert result == SENTINEL_JPG
