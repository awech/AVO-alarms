"""Unit tests for ``volc_alarms.alarms.VAA.detection``.

These call the VAA parsing helpers directly with crafted advisory text / field
dicts. No network is used (``download_mesonet_vaa_list`` / ``fetch_vaa_page`` /
``process_vaa_id`` hit the mesonet API and are covered via the integration path).

Covered:
* text_to_latlon    — degree/minute string -> decimal lat/lon (west negative)
* parse_vaa_fields  — LABEL: value parsing, longest-label preference, header
* parse_vaa_dtg     — 8- and 6-digit DTG -> UTC timestamp
* process_polygons  — single/multi-ring parsing, level text, time/MOV tokens,
                      per-ring NO VA EXP, and empty/missing/non-string -> []
* get_extent        — bounding box centered on the ring coordinates
"""

from __future__ import annotations

import numpy as np
import pytest

from volc_alarms.alarms.VAA.detection import (
    get_extent,
    parse_vaa_dtg,
    parse_vaa_fields,
    process_polygons,
    text_to_latlon,
)

pytestmark = pytest.mark.unit

OBS = "OBS VA CLD"
FCST_6HR = "FCST VA CLD +6HR"

# A single ring: SFC/060 bounds + 7 coordinate pairs (real MT KATMAI field).
MT_KATMAI_CLD = (
    "SFC/060 "
    "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
    "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)
MT_KATMAI_PAIRS = [
    "N5825 W15450",
    "N5753 W15414",
    "N5741 W15329",
    "N5717 W15405",
    "N5741 W15459",
    "N5818 W15524",
    "N5825 W15450 STNR",
]

RING1_PAIRS = ["N4941 W16417", "N4750 W16033", "N4834 W15601", "N4941 W16417"]
RING2_PAIRS = ["N5723 E17430", "N5448 W17024", "N5723 E17430"]
RING1_COORDS = " - ".join(RING1_PAIRS)
RING2_COORDS = " - ".join(RING2_PAIRS)


def _latlon(pairs):
    lats, lons = [], []
    for pr in pairs:
        lat, lon = text_to_latlon(pr)
        lats.append(lat)
        lons.append(lon)
    return lons, lats


# ---------------------------------------------------------------------------
# text_to_latlon
# ---------------------------------------------------------------------------
def test_text_to_latlon_converts_degrees_minutes_to_decimal():
    """text_to_latlon converts a 'N.. W..' token to decimal degrees (west negative)."""
    lat, lon = text_to_latlon("N5825 W15450")
    assert lat == pytest.approx(58.416666666666664)
    assert lon == pytest.approx(-154.83333333333334)


# ---------------------------------------------------------------------------
# parse_vaa_fields
# ---------------------------------------------------------------------------
def test_parse_vaa_fields_splits_labels_and_values():
    """parse_vaa_fields maps each 'LABEL:' to its value and collects the header."""
    text = (
        "FVAK21 PAWU 010858\n"
        "VA ADVISORY\n"
        "DTG: 20250101/0858Z\n"
        "VAAC: ANCHORAGE\n"
        "VOLCANO: PAVLOF 312030\n"
    )
    vaa = parse_vaa_fields(text)
    assert vaa["DTG"] == "20250101/0858Z"
    assert vaa["VAAC"] == "ANCHORAGE"
    assert vaa["VOLCANO"] == "PAVLOF 312030"
    assert "VA ADVISORY" in vaa["header"]


def test_parse_vaa_fields_prefers_longest_matching_label():
    """parse_vaa_fields matches 'OBS VA DTG' rather than the shorter 'DTG'."""
    text = "DTG: 20250101/0858Z\nOBS VA DTG: 20250101/0900Z\n"
    vaa = parse_vaa_fields(text)
    assert vaa["OBS VA DTG"] == "20250101/0900Z"
    assert vaa["DTG"] == "20250101/0858Z"


# ---------------------------------------------------------------------------
# parse_vaa_dtg
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "dtg, iso",
    [
        ("20250101/0858Z", "2025-01-01T08:58:00+00:00"),
        ("250101/0858Z", "2025-01-01T08:58:00+00:00"),
    ],
)
def test_parse_vaa_dtg_handles_8_and_6_digit_dates(dtg, iso):
    """parse_vaa_dtg parses both full and abbreviated DTG strings to a UTC time."""
    assert parse_vaa_dtg(dtg).isoformat() == iso


# ---------------------------------------------------------------------------
# process_polygons — single ring
# ---------------------------------------------------------------------------
def test_process_polygons_parses_single_ring_with_level():
    """process_polygons returns one ring with parsed coords and '0 - 6,000 ft' level."""
    groups = process_polygons({OBS: MT_KATMAI_CLD}, OBS)
    lons, lats = _latlon(MT_KATMAI_PAIRS)
    assert groups == [(lons, lats, "0 - 6,000 ft")]


@pytest.mark.parametrize(
    "level, expected_txt",
    [
        ("SFC/FL060", "0 - 6,000 ft"),
        ("FL200/FL300", "20,000 - 30,000 ft"),
        ("060/FL200", "6,000 - 20,000 ft"),
        ("060/090", "6,000 - 9,000 ft"),
    ],
)
def test_process_polygons_renders_level_text_for_bound_variants(level, expected_txt):
    """process_polygons derives the flight-level text regardless of FL/bare/SFC bounds."""
    field = f"{level} " + " - ".join(MT_KATMAI_PAIRS)
    groups = process_polygons({OBS: field}, OBS)
    assert len(groups) == 1
    assert groups[0][2] == expected_txt


# ---------------------------------------------------------------------------
# process_polygons — multi-ring, time token, MOV token, NO VA EXP
# ---------------------------------------------------------------------------
def test_process_polygons_parses_two_rings_with_motion_tokens():
    """process_polygons returns one group per ring, ignoring the MOV motion tokens."""
    field = (
        "FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 " + RING2_COORDS + " MOV SE 50KT"
    )
    groups = process_polygons({OBS: field}, OBS)

    lons1, lats1 = _latlon(RING1_PAIRS)
    lons2, lats2 = _latlon(RING2_PAIRS)
    assert len(groups) == 2
    assert groups[0] == (lons1, lats1, "10,000 - 34,000 ft")
    assert groups[1] == (lons2, lats2, "10,000 - 28,000 ft")
    # The MOV direction/speed never leaks into the coordinate lists.
    assert len(groups[0][0]) == len(RING1_PAIRS)
    assert len(groups[1][0]) == len(RING2_PAIRS)


@pytest.mark.parametrize("stamp", ["01/0858Z", "01/0858"])
def test_process_polygons_skips_leading_time_token(stamp):
    """process_polygons ignores a leading DD/HHMM(Z) forecast time token."""
    field = (
        f"{stamp} FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 NO VA EXP"
    )
    groups = process_polygons({FCST_6HR: field}, FCST_6HR)
    lons, lats = _latlon(RING1_PAIRS)
    # Only the real ring is returned; the NO VA EXP sub-polygon is skipped.
    assert groups == [(lons, lats, "10,000 - 34,000 ft")]


# ---------------------------------------------------------------------------
# process_polygons — empty / missing / non-string -> []
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vaa, field",
    [
        ({OBS: "VA NOT IDENTIFIABLE "}, OBS),
        ({FCST_6HR: "NO VA EXP"}, FCST_6HR),
        ({}, OBS),
        ({OBS: 12345}, OBS),
        ({OBS: None}, OBS),
        ({OBS: ["N5825 W15450"]}, OBS),
    ],
)
def test_process_polygons_returns_empty_list_for_no_ring(vaa, field):
    """process_polygons returns [] for no-coordinate, missing, or non-string fields."""
    assert process_polygons(vaa, field) == []


# ---------------------------------------------------------------------------
# get_extent
# ---------------------------------------------------------------------------
def test_get_extent_returns_box_around_coordinates():
    """get_extent returns a [lonmin, lonmax, latmin, latmax] box enclosing the coords."""
    lons, lats = _latlon(RING1_PAIRS)
    lonmin, lonmax, latmin, latmax = get_extent(np.array(lons), np.array(lats))
    assert lonmin < lonmax
    assert latmin < latmax
    # Box brackets the coordinate centroid.
    assert latmin < np.mean(lats) < latmax
