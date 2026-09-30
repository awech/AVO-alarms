"""Smoke test for ``volc_alarms.alarms.Swarm.figure.make_figure``.

``make_figure`` draws a map of the swarm events + a magnitude stem plot over
time, optionally overlaying the stations that recorded picks (downloaded per
event, wrapped in try/except so a download failure just skips that overlay). It
reads the swarm DataFrame's lat/lon/time/mag/depth/v_name/param_duration.

The per-event hypocenter-XML download is faked to return an empty catalog (so the
station overlay is skipped without network), and ``save_file`` is mocked to a
sentinel so no jpg is written; matplotlib runs headless on Agg. Like the other
figure tests this is a *smoke* test: it asserts the render runs end to end and
returns a path.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from obspy import Catalog, UTCDateTime

from volc_alarms.alarms.Swarm import figure as swarm_figure

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2026-09-23T21:30:00")
SENTINEL_JPG = "/tmp/__sentinel_swarm_figure__.jpg"


def _swarm(n=12, with_nan_mag=True):
    """A crafted swarm DataFrame shaped like get_swarms output (near Spurr)."""
    lat0, lon0 = 61.2989, -152.2539
    times = pd.to_datetime(
        [pd.Timestamp("2026-09-23 19:30:00") + pd.Timedelta(minutes=10 * i) for i in range(n)]
    )
    mags = [round(0.5 + 0.1 * i, 1) for i in range(n)]
    if with_nan_mag:
        mags[-1] = np.nan  # exercise the "unassigned magnitude" branch
    return pd.DataFrame(
        {
            "event_id": [f"s{i}" for i in range(n)],
            "time": times,
            "latitude": [lat0 + 0.002 * (i % 3) for i in range(n)],
            "longitude": [lon0 + 0.002 * (i % 2) for i in range(n)],
            "depth": [3.0 + 0.2 * i for i in range(n)],
            "mag": mags,
            "v_name": ["Spurr"] * n,
            "param_duration": [86400.0] * n,
        }
    )


def _config():
    return SimpleNamespace(alarm_name="Earthquake Swarm", DURATION=86400)


@pytest.fixture
def wired(monkeypatch):
    """Fake the per-event XML download (empty catalog) + sentinel save_file."""
    monkeypatch.setattr(
        swarm_figure.downloading, "download_hypocenter_xml", lambda url: Catalog()
    )
    monkeypatch.setattr(swarm_figure.plotting, "save_file", lambda *a, **k: SENTINEL_JPG)


def test_make_figure_runs_and_returns_path(wired):
    """make_figure renders the swarm map + stem plot and returns the saved path."""
    result = swarm_figure.make_figure(_swarm(), T0, _config(), test=False)
    assert result == SENTINEL_JPG


def test_make_figure_handles_all_events_with_magnitude(wired):
    """make_figure also renders when every event has a magnitude (no NaN branch)."""
    result = swarm_figure.make_figure(_swarm(with_nan_mag=False), T0, _config(), test=False)
    assert result == SENTINEL_JPG
