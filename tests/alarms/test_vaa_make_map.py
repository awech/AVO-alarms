"""Integration scenario for VAA ``make_map()`` under the multi-ring list contract.

Task 3.3 of the ``vaa-resuspended-ash-polygon-parsing`` bugfix spec:
``process_polygons()`` now returns a LIST of ``(lons, lats, level_txt)`` rings
per field, and ``make_map()`` plots each ring as its own line (one legend entry
per field) and builds a multi-level title from all distinct OBS levels.

These tests call ``make_map(vaa, config, test=False)`` directly with crafted
``vaa`` dicts built from the real production two-ring OBS field and the
``01/0858Z`` forecast field that crashed the unfixed code. Real rendering / disk
side effects are avoided by mocking ``figure.plotting.save_file`` to return a
sentinel path (so no jpg is written and no dpi=300 raster is produced).
Matplotlib already uses the headless "Agg" backend (set on import of
``volc_alarms.utils.plotting``), so the cartopy render path runs deterministically
without a display.

**Validates: Requirements 2.10, 2.11, 3.5**
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import matplotlib.pyplot as plt
import pytest

from volc_alarms.alarms.VAA import figure as vaa_figure

OBS_FIELD = "OBS VA CLD"
FCST_6HR = "FCST VA CLD +6HR"
FCST_12HR = "FCST VA CLD +12HR"
FCST_18HR = "FCST VA CLD +18HR"

# Real production TWO-RING OBS VA CLD field: two sub-polygons, each with its own
# FL bounds and its own coordinate ring, and a trailing MOV <DIR> <N>KT motion
# token that must NOT be parsed as a coordinate.
TWO_RING_OBS_CLD = (
    "FL100/FL340 N4941 W16417 - N4750 W16033 - N4834 W15601 - "
    "N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 N5723 E17430 - N5448 W17024 - N5723 E17430 MOV SE 50KT"
)

# Real production forecast field that crashed the unfixed code with
# ``ValueError: could not convert string to float: '-FC/060'``: a leading
# ``01/0858Z`` time token, one real FL100/FL340 ring, then a per-sub-polygon
# ``NO VA EXP`` that must be skipped without dropping the sibling.
FCST_6HR_CLD = (
    "01/0858Z FL100/FL340 N4941 W16417 - N4750 W16033 - N4834 W15601 - "
    "N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 NO VA EXP"
)

SENTINEL_JPG = "/tmp/__sentinel_vaa_figure__.jpg"

# Expected ring counts for the crafted advisory below.
OBS_RING_COUNT = 2   # two-ring OBS field
FCST_6HR_RING_COUNT = 1  # one real ring; NO VA EXP sub-polygon skipped
TOTAL_POLYGON_LINES = OBS_RING_COUNT + FCST_6HR_RING_COUNT  # 3

# The distinct OBS levels, comma-separated, that make_map places in the title.
EXPECTED_LEVELS = "10,000 - 34,000 ft, 10,000 - 28,000 ft"


def _bug_condition_vaa():
    """A crafted advisory: real two-ring OBS field + 01/0858Z forecast field."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: TWO_RING_OBS_CLD,
        FCST_6HR: FCST_6HR_CLD,
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


# A single valid OBS ring used for the malformed-PSN regression case. The PSN
# ``N5816 W154057`` is the real malformed upstream value: a 7-char longitude
# that text_to_latlon mis-reads as -1540.95, which would otherwise crash cartopy.
MALFORMED_PSN = "N5816 W154057"
SINGLE_RING_OBS_CLD = (
    "SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - "
    "N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)


def _malformed_psn_vaa():
    """A crafted advisory: one valid OBS ring + a malformed out-of-range PSN."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": MALFORMED_PSN,
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: SINGLE_RING_OBS_CLD,
        FCST_6HR: "NO VA EXP",
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _valid_psn_vaa():
    """A crafted advisory: one valid OBS ring + a valid in-range PSN."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: SINGLE_RING_OBS_CLD,
        FCST_6HR: "NO VA EXP",
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _no_coordinate_vaa():
    """A genuine no-coordinate advisory: every cloud field lacks coordinates."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: "VA NOT IDENTIFIABLE ",
        FCST_6HR: "NO VA EXP",
        FCST_12HR: "NO VA EXP",
        FCST_18HR: "NO VA EXP",
    }


def _is_polygon_line(line):
    """A plotted polygon ring line vs the volcano triangle marker.

    make_map plots the volcano location via ``ax.plot(v_lon, v_lat, "^", ...)``
    (a marker, no connecting line). Each polygon ring is plotted with a
    linestyle and no marker. Distinguish rings from the triangle by marker.
    """
    return line.get_marker() in (None, "None", "")


@pytest.fixture
def mock_save_file(monkeypatch):
    """Replace ``figure.plotting.save_file`` with a recording sentinel.

    Captures the passed args and the live ``fig`` so tests can inspect the Axes
    (lines / legend / title) without writing a jpg or rendering at dpi=300.
    """
    calls = []

    def _fake_save_file(fig, config, dpi=250, test=False):
        ax = fig.axes[0]
        handles, labels = ax.get_legend_handles_labels()
        calls.append(
            {
                "config": config,
                "dpi": dpi,
                "test": test,
                "title": ax.get_title(),
                "legend_labels": list(labels),
                "polygon_lines": [ln for ln in ax.get_lines() if _is_polygon_line(ln)],
                "all_lines": list(ax.get_lines()),
            }
        )
        return SENTINEL_JPG

    monkeypatch.setattr(vaa_figure.plotting, "save_file", _fake_save_file)
    return calls


@pytest.fixture
def config():
    """A minimal config stub; only forwarded to the (mocked) save_file."""
    return SimpleNamespace(alarm_name="VAA")


def test_bug_condition_advisory_generates_figure(mock_save_file, config):
    """Req 2.10 - a multi-ring advisory (incl. the 01/0858Z forecast) makes a figure.

    The fixed code does NOT take the "No polygons to plot" path; it renders and
    returns the (mocked) save_file result rather than ``[]``. save_file is called
    exactly once with dpi=300.
    """
    vaa = _bug_condition_vaa()

    result = vaa_figure.make_map(vaa, config, test=False)

    assert result == SENTINEL_JPG
    assert result != []
    assert len(mock_save_file) == 1
    assert mock_save_file[0]["dpi"] == 300
    assert mock_save_file[0]["test"] is False


def test_each_ring_is_a_separate_line_with_one_legend_entry_per_field(
    mock_save_file, config
):
    """Req 2.10 - each ring is its own line; the legend has one entry per field.

    Total polygon lines == total rings across fields (OBS 2 + 6HR 1 = 3),
    excluding the volcano triangle marker. The legend shows exactly the
    per-field labels (one per field with >= 1 ring: 'Observed', '6H Forecast'),
    NOT one entry per ring - the extra rings use the '_nolegend_' label.
    """
    vaa = _bug_condition_vaa()

    result = vaa_figure.make_map(vaa, config, test=False)
    assert result == SENTINEL_JPG

    captured = mock_save_file[0]

    # One line per ring, excluding the triangle marker.
    assert len(captured["polygon_lines"]) == TOTAL_POLYGON_LINES  # 3

    # Legend labels are the per-field labels only (one per field with rings),
    # never the '_nolegend_' sentinel and never one-per-ring.
    assert captured["legend_labels"] == ["Observed", "6H Forecast"]
    assert "_nolegend_" not in captured["legend_labels"]
    assert len(captured["legend_labels"]) == 2  # two fields have rings, not 3


def test_title_lists_all_distinct_obs_levels_comma_separated(mock_save_file, config):
    """Req 2.11 - the title lists both distinct OBS levels, comma-separated."""
    vaa = _bug_condition_vaa()

    result = vaa_figure.make_map(vaa, config, test=False)
    assert result == SENTINEL_JPG

    title = mock_save_file[0]["title"]
    assert EXPECTED_LEVELS in title
    # Both individual levels are present.
    assert "10,000 - 34,000 ft" in title
    assert "10,000 - 28,000 ft" in title


def test_no_coordinate_advisory_skips_figure(mock_save_file, config, caplog):
    """Req 3.5 - a genuine no-coordinate advisory still skips figure generation.

    make_map logs "No polygons to plot. Not generating figure." and returns
    ``[]`` without ever calling save_file.
    """
    vaa = _no_coordinate_vaa()

    with caplog.at_level(logging.WARNING):
        result = vaa_figure.make_map(vaa, config, test=False)

    assert result == []
    assert len(mock_save_file) == 0
    assert "No polygons to plot. Not generating figure." in caplog.text


def test_malformed_psn_still_generates_figure(mock_save_file, config, caplog):
    """A malformed/out-of-range PSN must not crash make_map.

    The real upstream ``N5816 W154057`` PSN is mis-read as an out-of-range
    longitude that used to crash cartopy. make_map must instead render from the
    (valid) polygon coordinates: it returns the sentinel (not ``[]``), calls
    save_file once, logs a WARNING mentioning the raw PSN, and SKIPS the volcano
    triangle marker while still plotting the polygon ring line(s).
    """
    vaa = _malformed_psn_vaa()

    with caplog.at_level(logging.WARNING):
        result = vaa_figure.make_map(vaa, config, test=False)

    assert result == SENTINEL_JPG
    assert result != []
    assert len(mock_save_file) == 1

    # The warning mentions the raw malformed PSN value.
    assert MALFORMED_PSN in caplog.text

    captured = mock_save_file[0]

    # The polygon ring line IS present ...
    assert len(captured["polygon_lines"]) == 1
    # ... but the volcano triangle marker is NOT plotted.
    triangle_lines = [ln for ln in captured["all_lines"] if ln.get_marker() == "^"]
    assert triangle_lines == []


def test_valid_psn_plots_triangle_marker(mock_save_file, config):
    """The normal path is unregressed: a valid PSN still plots the triangle.

    make_map renders, returns the sentinel, and includes the ``^`` volcano
    marker alongside the polygon ring line.
    """
    vaa = _valid_psn_vaa()

    result = vaa_figure.make_map(vaa, config, test=False)

    assert result == SENTINEL_JPG
    captured = mock_save_file[0]

    # The polygon ring line is present.
    assert len(captured["polygon_lines"]) == 1
    # The volcano triangle marker IS plotted on the valid path.
    triangle_lines = [ln for ln in captured["all_lines"] if ln.get_marker() == "^"]
    assert len(triangle_lines) == 1
