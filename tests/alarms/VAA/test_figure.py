"""Unit tests for ``volc_alarms.alarms.VAA.figure.make_map``.

These call ``make_map(vaa, config)`` directly with crafted ``vaa`` dicts. Disk
and raster side effects are avoided by mocking ``figure.plotting.save_file`` to
return a sentinel and capture the live Axes (lines / legend / title). matplotlib
already uses the headless "Agg" backend, so the cartopy render path runs without
a display.

Covered:
* make_map — a multi-ring advisory renders one line per ring, one legend entry
             per field, and a title listing the distinct OBS levels
* make_map — a genuine no-coordinate advisory skips figure generation (returns [])
* make_map — a malformed/out-of-range PSN still renders (skips the volcano marker)
* make_map — a valid PSN plots the volcano triangle marker
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from volc_alarms.alarms.VAA import figure as vaa_figure

pytestmark = pytest.mark.unit

OBS = "OBS VA CLD"
FCST_6HR = "FCST VA CLD +6HR"
FCST_12HR = "FCST VA CLD +12HR"
FCST_18HR = "FCST VA CLD +18HR"

SENTINEL_JPG = "/tmp/__sentinel_vaa_figure__.jpg"

TWO_RING_OBS_CLD = (
    "FL100/FL340 N4941 W16417 - N4750 W16033 - N4834 W15601 - "
    "N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 N5723 E17430 - N5448 W17024 - N5723 E17430 MOV SE 50KT"
)
FCST_6HR_CLD = (
    "01/0858Z FL100/FL340 N4941 W16417 - N4750 W16033 - N4834 W15601 - "
    "N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 NO VA EXP"
)
SINGLE_RING_OBS_CLD = (
    "SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - "
    "N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)
# Real malformed upstream value: a 7-char longitude text_to_latlon mis-reads.
MALFORMED_PSN = "N5816 W154057"


def _multi_field_vaa():
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        OBS: TWO_RING_OBS_CLD,
        FCST_6HR: FCST_6HR_CLD,
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _single_ring_vaa(psn):
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": psn,
        "time": "2025-01-01T00:00:00",
        OBS: SINGLE_RING_OBS_CLD,
        FCST_6HR: "NO VA EXP",
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _no_coordinate_vaa():
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        OBS: "VA NOT IDENTIFIABLE ",
        FCST_6HR: "NO VA EXP",
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _is_ring_line(line):
    """A polygon ring line has a linestyle and no marker (vs the ^ volcano marker)."""
    return line.get_marker() in (None, "None", "")


@pytest.fixture
def captured_figure(monkeypatch):
    """Mock save_file to capture the live Axes without writing a jpg."""
    calls = []

    def _fake_save_file(fig, config, dpi=250, test=False):
        ax = fig.axes[0]
        _, labels = ax.get_legend_handles_labels()
        calls.append(
            {
                "dpi": dpi,
                "test": test,
                "title": ax.get_title(),
                "legend_labels": list(labels),
                "ring_lines": [ln for ln in ax.get_lines() if _is_ring_line(ln)],
                "marker_lines": [ln for ln in ax.get_lines() if ln.get_marker() == "^"],
            }
        )
        return SENTINEL_JPG

    monkeypatch.setattr(vaa_figure.plotting, "save_file", _fake_save_file)
    return calls


@pytest.fixture
def config():
    return SimpleNamespace(alarm_name="VAA")


def test_make_map_plots_one_line_per_ring_with_one_legend_entry_per_field(
    captured_figure, config
):
    """make_map draws a line per ring (OBS 2 + 6HR 1 = 3) with one legend label per field."""
    result = vaa_figure.make_map(_multi_field_vaa(), config, test=False)

    assert result == SENTINEL_JPG
    cap = captured_figure[0]
    assert len(cap["ring_lines"]) == 3
    assert cap["legend_labels"] == ["Observed", "6H Forecast"]
    assert "_nolegend_" not in cap["legend_labels"]


def test_make_map_title_lists_distinct_obs_levels(captured_figure, config):
    """make_map builds a title listing both distinct OBS levels, comma-separated."""
    vaa_figure.make_map(_multi_field_vaa(), config, test=False)
    title = captured_figure[0]["title"]
    assert "10,000 - 34,000 ft, 10,000 - 28,000 ft" in title


def test_make_map_skips_figure_for_no_coordinate_advisory(captured_figure, config, caplog):
    """make_map returns [] and never calls save_file when no polygons are present."""
    with caplog.at_level(logging.WARNING):
        result = vaa_figure.make_map(_no_coordinate_vaa(), config, test=False)

    assert result == []
    assert len(captured_figure) == 0
    assert "No polygons to plot. Not generating figure." in caplog.text


def test_make_map_renders_without_volcano_marker_for_malformed_psn(
    captured_figure, config, caplog
):
    """make_map still renders (skipping the triangle marker) when the PSN is out of range."""
    with caplog.at_level(logging.WARNING):
        result = vaa_figure.make_map(_single_ring_vaa(MALFORMED_PSN), config, test=False)

    assert result == SENTINEL_JPG
    assert MALFORMED_PSN in caplog.text
    cap = captured_figure[0]
    assert len(cap["ring_lines"]) == 1
    assert cap["marker_lines"] == []


def test_make_map_plots_volcano_marker_for_valid_psn(captured_figure, config):
    """make_map plots the ^ volcano triangle marker when the PSN is valid."""
    result = vaa_figure.make_map(_single_ring_vaa("N5817 W15498"), config, test=False)

    assert result == SENTINEL_JPG
    cap = captured_figure[0]
    assert len(cap["ring_lines"]) == 1
    assert len(cap["marker_lines"]) == 1
