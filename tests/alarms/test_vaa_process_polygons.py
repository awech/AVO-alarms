"""Bug condition exploration tests for VAA ``process_polygons()``.

These tests encode the EXPECTED (post-fix) behavior from Property 1 of the
``vaa-resuspended-ash-polygon-parsing`` bugfix spec: a cloud field with valid
polygon coordinates SHALL parse those coordinates and derive ``flight_level_txt``
regardless of whether either ``/``-separated level bound carries an ``FL`` prefix.

On the UNFIXED code these tests are EXPECTED TO FAIL - the failure confirms the
bug exists:

* Test case A (``SFC/060``) and C (``060/090``): the ``if "FL" in obs_text:``
  gate is skipped when no bound carries ``FL``, so empty ``lons``/``lats`` are
  returned (coordinate-parsing gate defect).
* Test case B (``060/FL200``): the ``FL``-anchored regex ``.*\\S+/FL\\S+`` still
  matches (the upper bound has ``FL``) but anchors on the ``/FL`` boundary, so
  the bare lower bound ``060`` is not stripped and is mis-parsed as the first
  coordinate pair (level-token regex defect).

The tests call ``process_polygons(vaa, field)`` directly with crafted ``vaa``
dicts - no network and no matplotlib rendering are required.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4**
"""

from __future__ import annotations

from volc_alarms.alarms.VAA.detection import process_polygons, text_to_latlon

FIELD = "OBS VA CLD"

# The MT KATMAI OBS VA CLD field: a bare/SFC level with 7 valid coordinate pairs.
MT_KATMAI_CLD = (
    "SFC/060 "
    "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
    "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)

# The seven coordinate tokens in the MT KATMAI field, used to compute expected
# lat/lon via the (unmodified) text_to_latlon helper.
MT_KATMAI_PAIRS = [
    "N5825 W15450",
    "N5753 W15414",
    "N5741 W15329",
    "N5717 W15405",
    "N5741 W15459",
    "N5818 W15524",
    "N5825 W15450 STNR",  # trailing STNR is stripped by text_to_latlon splitting
]


def _expected_latlon(pairs):
    lats, lons = [], []
    for pr in pairs:
        lat, lon = text_to_latlon(pr)
        lats.append(lat)
        lons.append(lon)
    return lons, lats


def test_case_a_sfc_bare_gate_mt_katmai():
    """Test case A - SFC/bare gate (MT KATMAI).

    ``SFC/060`` has no ``FL`` on either bound. The field carries 7 valid
    coordinate pairs and the level should render as ``0 - 6,000 ft``.

    UNFIXED: the ``if "FL" in obs_text:`` gate is skipped -> empty lists.
    """
    vaa = {FIELD: MT_KATMAI_CLD}

    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    # Bug condition counterexample: on unfixed code these are empty lists.
    assert len(lons) == len(lats) == 7
    assert flight_level_txt == "0 - 6,000 ft"


def test_case_b_mixed_bound_regex_060_fl200():
    """Test case B - mixed bound regex (``060/FL200``).

    The lower bound is bare and the upper bound carries ``FL``. The level token
    ``060/FL200`` must be stripped so it is never fed into ``text_to_latlon()``
    as a coordinate pair.

    UNFIXED: the ``.*\\S+/FL\\S+`` regex anchors on ``/FL200`` so the bare ``060``
    is not stripped; the first "pair" becomes ``060/FL200 N5825 W15450`` which is
    mis-parsed, corrupting the coordinates.
    """
    field_text = (
        "060/FL200 "
        "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
        "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
    )
    vaa = {FIELD: field_text}

    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    # The seven real coordinate pairs, computed via the unmodified helper.
    expected_lons, expected_lats = _expected_latlon(MT_KATMAI_PAIRS)

    # Level token must be stripped, not mis-parsed as a coordinate pair.
    assert len(lons) == len(lats) == 7
    assert lons == expected_lons
    assert lats == expected_lats
    # The first parsed coordinate must be the real N5825 W15450, never a value
    # derived from the corrupted "060/FL200 N5825 W15450" token.
    assert (lats[0], lons[0]) == text_to_latlon("N5825 W15450")
    assert flight_level_txt == "6,000 - 20,000 ft"


def test_case_c_both_bare_060_090():
    """Test case C - both bare (``060/090``).

    Neither bound carries ``FL``. Coordinates must parse and the level should
    render as ``6,000 - 9,000 ft``.

    UNFIXED: the ``if "FL" in obs_text:`` gate is skipped -> empty lists.
    """
    field_text = (
        "060/090 "
        "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
        "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
    )
    vaa = {FIELD: field_text}

    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    assert len(lons) == len(lats) == 7
    assert flight_level_txt == "6,000 - 9,000 ft"
