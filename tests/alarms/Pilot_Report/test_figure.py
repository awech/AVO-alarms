"""Smoke test for ``volc_alarms.alarms.Pilot_Report.figure.plot_fig``.

``plot_fig`` draws a cartopy map centered on a pilot report, marks the report
location, and captions it with the flight level + parsed pilot remark. It reads
only the ``pirep_row`` fields (``lat``/``lon``/``time``/``FL``/``REPORT``) plus
the volcano list, so no downloads or images are needed.

``save_file`` is mocked to a sentinel so no jpg is written; matplotlib runs
headless on Agg. Like the other figure tests this is a *smoke* test: it asserts
the render runs end to end, returns a path, and captions/marks the report.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from volc_alarms.alarms.Pilot_Report import figure as pirep_figure

pytestmark = pytest.mark.unit

SENTINEL_JPG = "/tmp/__sentinel_pilot_report_figure__.jpg"

# Fields from the recorded Shishaldin ash PIREP (2026-09-11 00:39 UTC).
REPORT = "CDB UUA /OV CDB224051/TM 0039/FL380/TP B748/RM VA SHISHALDIN TO 20MI E. LIGHT GREY TOPS EST 150. NO SMELL OF SULFUR /ZAN/"


def _pirep_row():
    return pd.Series(
        {
            "time": pd.Timestamp("2026-09-11 00:39:00"),
            "lat": 54.5885,
            "lon": -163.7547,
            "FL": 38000.0,
            "REPORT": REPORT,
        }
    )


def _config():
    return SimpleNamespace(alarm_name="PIREP")


@pytest.fixture
def captured(monkeypatch):
    """Capture the live figure/Axes via a mocked save_file (no jpg written)."""
    calls = []

    def _fake_save_file(fig, config, test=False, dpi=250):
        ax = fig.axes[0]
        calls.append(
            {
                "test": test,
                "title": ax.get_title(),
                "markers": [ln for ln in ax.get_lines() if ln.get_marker() == "o"],
            }
        )
        return SENTINEL_JPG

    monkeypatch.setattr(pirep_figure.plotting, "save_file", _fake_save_file)
    return calls


def test_plot_fig_runs_and_returns_path(captured):
    """plot_fig renders the report map and returns the saved-figure path."""
    result = pirep_figure.plot_fig(_pirep_row(), _config(), test=False)
    assert result == SENTINEL_JPG


def test_plot_fig_titles_flight_level_and_marks_report(captured):
    """plot_fig titles the flight level and plots the report-location marker."""
    pirep_figure.plot_fig(_pirep_row(), _config(), test=False)
    cap = captured[0]
    assert "38,000 feet" in cap["title"]
    assert cap["markers"], "expected the report-location 'o' marker"
