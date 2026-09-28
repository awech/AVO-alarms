"""Unit tests for the ``list-alerts`` command-line entry point.

Cover argument parsing, the start/end/duration validation rules, the query-dict
assembly, and the dispatch into ``alarming.filtered_list`` (mocked; no DB).

Covered:
* parse_args     — optional alarm/volcano/test/start/end/duration flags
* main()         — start-after-end error; start+end+duration error; duration
                   parsing (h/d/m); query-dict assembly and filtered_list call
"""

from __future__ import annotations

import sys

import pytest

from volc_alarms.scripts import list_alerts as cli

pytestmark = pytest.mark.unit


@pytest.fixture
def wired(monkeypatch):
    """Mock env loading and capture the filtered_list query dict."""
    captured = {}
    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)

    def _filtered_list(query_dict, test=False):
        captured["query"] = query_dict
        captured["test"] = test

    monkeypatch.setattr(cli.alarming, "filtered_list", _filtered_list)
    return captured


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["list-alerts", *argv])
    cli.main()


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------
def test_parse_args_reads_optional_filters(monkeypatch):
    """parse_args captures alarm/volcano/test and the time-range flags."""
    monkeypatch.setattr(
        sys, "argv",
        ["list-alerts", "-a", "Pavlof_RSAM", "-v", "Pavlof", "-t", "-dt", "3h"],
    )
    args = cli.parse_args()
    assert args.alarm == "Pavlof_RSAM"
    assert args.volcano == "Pavlof"
    assert args.test is True
    assert args.duration == "3h"


# ---------------------------------------------------------------------------
# main — validation
# ---------------------------------------------------------------------------
def test_main_errors_when_start_after_end(wired, monkeypatch):
    """main() raises ValueError when the start time is after the end time."""
    with pytest.raises(ValueError, match="Start time must be before end time"):
        _run(monkeypatch, ["-s", "202501020000", "-e", "202501010000"])


def test_main_errors_on_start_end_and_duration(wired, monkeypatch):
    """main() raises ValueError when start, end, and duration are all provided."""
    with pytest.raises(ValueError, match="Cannot have start, end AND duration"):
        _run(monkeypatch, ["-s", "202501010000", "-e", "202501020000", "-dt", "3h"])


def test_main_errors_on_invalid_duration_unit(wired, monkeypatch):
    """main() raises ValueError for a duration without a valid h/d/m suffix."""
    with pytest.raises(ValueError, match="Invalid duration format"):
        _run(monkeypatch, ["-dt", "3y"])


# ---------------------------------------------------------------------------
# main — query assembly + dispatch
# ---------------------------------------------------------------------------
def test_main_builds_query_from_alarm_and_volcano(wired, monkeypatch):
    """main() maps --alarm/--volcano (underscores->spaces) into the query dict."""
    _run(monkeypatch, ["-a", "Pavlof_RSAM", "-v", "Mount_Spurr", "-t"])

    assert wired["query"]["alarm_id"] == "Pavlof RSAM"
    assert wired["query"]["volcano"] == "Mount Spurr"
    assert wired["test"] is True


def test_main_start_plus_duration_sets_end(wired, monkeypatch):
    """main() with start + duration computes the end time in the query dict."""
    _run(monkeypatch, ["-s", "202501010000", "-dt", "2h"])
    q = wired["query"]
    assert q["t1"] == "2025-01-01T00:00:00"
    assert q["t2"] == "2025-01-01T02:00:00"
