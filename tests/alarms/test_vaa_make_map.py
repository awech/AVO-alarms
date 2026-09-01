"""Integration scenario for VAA ``make_map()`` after the FL-prefix fix.

Task 4 of the ``vaa-resuspended-ash-polygon-parsing`` bugfix spec: provide
integration coverage that the fix makes ``make_map()`` generate a figure for a
bug-condition advisory whose level bounds lack an ``FL`` prefix (``SFC/060``),
while a genuine no-coordinate advisory still skips figure generation.

These tests call ``make_map(vaa, config, test=False)`` directly with crafted
``vaa`` dicts. Real rendering / disk side effects are avoided by mocking
``figure.plotting.save_file`` to return a sentinel path (so no jpg is written
and no dpi=300 raster is produced). Matplotlib already uses the headless "Agg"
backend (set in ``volc_alarms.utils.plotting``), so the cartopy render path runs
deterministically without a display.

The frozen ``VAA_representative.json`` baseline and its harness
(``scenarios.py`` / ``test_regression.py``) are intentionally left untouched -
that harness patches figure builders out and drives the webpage-error path, so
it cannot assert that a figure IS produced.

**Validates: Requirements 2.5, 3.5**
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from volc_alarms.alarms.VAA import figure as vaa_figure
from volc_alarms.alarms.VAA.detection import process_polygons

FIELD = "OBS VA CLD"

# A bug-condition advisory: SFC/060 level (no FL prefix on either bound) with 7
# valid coordinate pairs (the MT KATMAI OBS VA CLD field).
MT_KATMAI_CLD = (
    "SFC/060 "
    "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
    "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)

SENTINEL_JPG = "/tmp/__sentinel_vaa_figure__.jpg"


def _bug_condition_vaa():
    """A crafted advisory whose OBS cloud level is SFC/060 (bug condition)."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        FIELD: MT_KATMAI_CLD,
        "FCST VA CLD +6HR": "NO VA EXP",
        "FCST VA CLD +12HR": "NO VA EXP",
        "FCST VA CLD +18HR": "NO VA EXP",
    }


def _no_coordinate_vaa():
    """A genuine no-coordinate advisory: every cloud field lacks coordinates."""
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "PSN": "N5817 W15498",
        "time": "2025-01-01T00:00:00",
        FIELD: "VA NOT IDENTIFIABLE ",
        "FCST VA CLD +6HR": "NO VA EXP",
        "FCST VA CLD +12HR": "NO VA EXP",
        "FCST VA CLD +18HR": "NO VA EXP",
    }


@pytest.fixture
def mock_save_file(monkeypatch):
    """Replace ``figure.plotting.save_file`` with a recording sentinel.

    Avoids the real jpg write / dpi=300 raster while still letting us assert
    whether the save path was reached.
    """
    calls = []

    def _fake_save_file(fig, config, dpi=250, test=False):
        calls.append({"config": config, "dpi": dpi, "test": test})
        return SENTINEL_JPG

    monkeypatch.setattr(vaa_figure.plotting, "save_file", _fake_save_file)
    return calls


@pytest.fixture
def config():
    """A minimal config stub; only forwarded to the (mocked) save_file."""
    return SimpleNamespace(alarm_name="VAA")


def test_bug_condition_advisory_generates_figure(mock_save_file, config):
    """Req 2.5 - an SFC/060 advisory with valid coordinates produces a figure.

    The fix means make_map does NOT take the "No polygons to plot" path; it
    renders and returns the (mocked) save_file result rather than ``[]``.
    """
    vaa = _bug_condition_vaa()

    result = vaa_figure.make_map(vaa, config, test=False)

    # A figure was generated: save_file returned the sentinel (not the empty
    # "no polygons" return value).
    assert result == SENTINEL_JPG
    assert result != []
    assert len(mock_save_file) == 1
    assert mock_save_file[0]["dpi"] == 300
    assert mock_save_file[0]["test"] is False


def test_no_coordinate_advisory_skips_figure(mock_save_file, config, caplog):
    """Req 3.5 - a genuine no-coordinate advisory still skips figure generation.

    make_map logs "No polygons to plot. Not generating figure." and returns
    ``[]`` without ever calling save_file.
    """
    vaa = _no_coordinate_vaa()

    with caplog.at_level(logging.WARNING):
        result = vaa_figure.make_map(vaa, config, test=False)

    assert result == []
    # save_file must NOT have been reached.
    assert len(mock_save_file) == 0
    assert "No polygons to plot. Not generating figure." in caplog.text


def test_title_level_uses_new_flight_level_txt():
    """Req 2.5 - the OBS level renders via the new flight_level_txt.

    For SFC/060 the fix yields "0 - 6,000 ft", which make_map places in the
    figure title. Assert both the parsed level text and the rendered title.
    """
    vaa = _bug_condition_vaa()

    _lons, _lats, flight_level_txt = process_polygons(vaa, FIELD)
    assert flight_level_txt == "0 - 6,000 ft"

    # Confirm the same value flows into the rendered title. Reach the save path
    # via a local sentinel so no jpg is written.
    import matplotlib.pyplot as plt

    captured = {}

    def _capture_save_file(fig, config, dpi=250, test=False):
        # The single Axes carries the title make_map set.
        captured["title"] = fig.axes[0].get_title()
        plt.close(fig)
        return SENTINEL_JPG

    original = vaa_figure.plotting.save_file
    vaa_figure.plotting.save_file = _capture_save_file
    try:
        result = vaa_figure.make_map(vaa, SimpleNamespace(alarm_name="VAA"), test=False)
    finally:
        vaa_figure.plotting.save_file = original

    assert result == SENTINEL_JPG
    assert "0 - 6,000 ft" in captured["title"]
