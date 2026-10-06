"""Unit tests for ``volc_alarms.alarms.Lightning.figure.plot_fig``.

``plot_fig`` builds a cartopy map for one volcano: a base map + volcano markers,
the source-volcano triangle, and a time-colored scatter of that volcano's recent
strokes (plus a colorbar and an orthographic inset). It reads lat/lon/name/time
from ``df.iloc[0]`` and colors the scatter by stroke time.

Disk and raster side effects are avoided by mocking ``figure.plotting.save_file``
to capture the live figure and return a sentinel path; matplotlib runs on the
headless "Agg" backend, so the real cartopy render path executes without a
display. These assert observable wiring (title, source marker, one scatter point
per stroke, test-flag pass-through), not exact pixels -- production wraps figure
generation in try/except and edits arrive as plotting tweaks.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from obspy import UTCDateTime

from volc_alarms.alarms.Lightning import figure as lightning_figure

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2026-08-31T21:00:00")
SENTINEL_JPG = "/tmp/__sentinel_lightning_figure__.jpg"


def _strokes(n=4):
    """n strokes near Edgecumbe, most-recent first (as run_alarm passes them)."""
    times = [pd.Timestamp("2026-08-31 20:58:00") - pd.Timedelta(minutes=5 * i) for i in range(n)]
    return pd.DataFrame(
        {
            "id": [f"L{i}" for i in range(n)],
            "time": pd.to_datetime(times),
            "v_name": ["Edgecumbe"] * n,
            "v_distance": [5.0 + 3.0 * i for i in range(n)],
            "api_vlat": [57.05] * n,
            "api_vlon": [-135.76] * n,
            "latitude": [57.00 - 0.02 * i for i in range(n)],
            "longitude": [-135.70 - 0.02 * i for i in range(n)],
        }
    )


def _config():
    return SimpleNamespace(alarm_name="Edgecumbe Lightning", dist2=100, duration=3600)


@pytest.fixture
def captured(monkeypatch):
    """Capture the live figure/Axes via a mocked save_file (no jpg written)."""
    calls = []

    def _fake_save_file(fig, config, test=False, dpi=250):
        ax = fig.axes[0]
        calls.append(
            {
                "test": test,
                "dpi": dpi,
                "title": ax.get_title(),
                "scatters": [c for c in ax.collections if len(c.get_offsets()) > 0],
                "markers": [ln for ln in ax.get_lines() if ln.get_marker() == "^"],
            }
        )
        return SENTINEL_JPG

    monkeypatch.setattr(lightning_figure.plotting, "save_file", _fake_save_file)
    return calls


def test_plot_fig_runs_and_returns_path(captured):
    """plot_fig completes the full cartopy render and returns the saved path."""
    result = lightning_figure.plot_fig(_strokes(), _config(), T0, test=False)
    assert result == SENTINEL_JPG


def test_plot_fig_titles_map_with_volcano_and_recent_time(captured):
    """The title names the source volcano and its most-recent stroke time."""
    lightning_figure.plot_fig(_strokes(), _config(), T0, test=False)
    title = captured[0]["title"]
    assert "Edgecumbe Lightning" in title
    # t_recent is df.iloc[0].time (the first row) rendered as 'YYYY-mm-dd HH:MM:SS'.
    assert "2026-08-31 20:58:00" in title


def test_plot_fig_plots_source_marker_and_one_point_per_stroke(captured):
    """plot_fig draws the source-volcano ^ marker and scatters every stroke."""
    n = 5
    lightning_figure.plot_fig(_strokes(n), _config(), T0, test=False)
    cap = captured[0]
    assert cap["markers"], "expected the source-volcano ^ marker"
    # The time-colored stroke scatter contributes one offset per stroke.
    assert any(len(s.get_offsets()) == n for s in cap["scatters"]), (
        f"expected a scatter of {n} strokes; "
        f"got offset counts {[len(s.get_offsets()) for s in cap['scatters']]}"
    )


def test_plot_fig_passes_test_flag_to_save_file(captured):
    """test=True reaches save_file (which applies the TEST watermark)."""
    lightning_figure.plot_fig(_strokes(), _config(), T0, test=True)
    assert captured[0]["test"] is True
