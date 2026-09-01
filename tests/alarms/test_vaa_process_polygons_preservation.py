r"""Preservation tests for VAA ``process_polygons()`` (Property 2).

These tests capture the BASELINE behavior of ``process_polygons()`` that the
``vaa-resuspended-ash-polygon-parsing`` bugfix MUST NOT change (Property 2,
Requirements 3.1-3.6). They cover the inputs where the bug condition does NOT
hold: fully ``FL``-prefixed levels, ``VA NOT IDENTIFIABLE``, ``NO VA EXP``,
missing / non-string fields, and the per-pair ``text_to_latlon()`` conversion.

Observation-first methodology
-----------------------------
The expected values asserted below were recorded by running the UNFIXED
``process_polygons()`` / ``text_to_latlon()`` and copying their actual outputs.
These tests are therefore EXPECTED TO PASS on the unfixed code (they capture the
baseline to preserve) and MUST continue to pass after the fix is applied.

Baseline outputs recorded on the UNFIXED code (field ``OBS VA CLD``), using the
coordinate polygon
``N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 -
N5741 W15459 - N5818 W15524 - N5825 W15450 STNR`` (7 pairs):

* ``SFC/FL060 <coords>``   -> 7 pairs, flight_level_txt == "0 - 6,000 ft"
* ``FL200/FL300 <coords>`` -> 7 pairs, flight_level_txt == "20,000 - 30,000 ft"
* ``"VA NOT IDENTIFIABLE "`` -> ([], [], "")
* missing field            -> ([], [], "")  (no error)
* non-string field value   -> ([], [], "")  (no error)
* ``FCST VA CLD +6HR`` == "NO VA EXP" -> ([], [], "")  (no coordinate pairs)
* text_to_latlon("N5825 W15450") -> (58.416666666666664, -154.83333333333334)
* text_to_latlon("N5753 W15414") -> (57.88333333333333, -154.23333333333332)

Note on tooling
---------------
The bugfix spec calls for property-based generation of the preservation cases,
but ``hypothesis`` is not installed in the ``dev-alarms`` environment. These
tests therefore use ``pytest`` parametrized fixed examples that enumerate the
representative baseline inputs instead of randomized generation. The assertions
still follow the observation-first methodology (recorded actual outputs).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""

from __future__ import annotations

import pytest

from volc_alarms.alarms.VAA.detection import process_polygons, text_to_latlon

FIELD = "OBS VA CLD"

# The shared 7-pair coordinate polygon used across the FL-prefixed baselines.
COORDS = (
    "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
    "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
)

# The seven coordinate tokens, used to compute the expected lon/lat sequence
# via the (unmodified) text_to_latlon helper.
COORD_PAIRS = [
    "N5825 W15450",
    "N5753 W15414",
    "N5741 W15329",
    "N5717 W15405",
    "N5741 W15459",
    "N5818 W15524",
    "N5825 W15450 STNR",  # trailing STNR is dropped by text_to_latlon splitting
]


def _expected_lons_lats(pairs):
    lats, lons = [], []
    for pr in pairs:
        lat, lon = text_to_latlon(pr)
        lats.append(lat)
        lons.append(lon)
    return lons, lats


# ---------------------------------------------------------------------------
# Req 3.1 - FL-prefixed levels parse coordinates and derive level text as before
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "level, expected_flight_level_txt",
    [
        ("SFC/FL060", "0 - 6,000 ft"),
        ("FL200/FL300", "20,000 - 30,000 ft"),
    ],
)
def test_fl_prefixed_levels_preserved(level, expected_flight_level_txt):
    """Fully/partly FL-prefixed levels: coordinates and level text unchanged.

    Baseline (unfixed): 7 coordinate pairs and the recorded level text.
    """
    vaa = {FIELD: f"{level} {COORDS}"}

    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_lons_lats(COORD_PAIRS)

    assert len(lons) == len(lats) == 7
    assert lons == expected_lons
    assert lats == expected_lats
    assert flight_level_txt == expected_flight_level_txt


# ---------------------------------------------------------------------------
# Req 3.2 - VA NOT IDENTIFIABLE returns empty lists / empty level text
# ---------------------------------------------------------------------------
def test_va_not_identifiable_preserved():
    """A ``VA NOT IDENTIFIABLE `` field returns ([], [], "")."""
    vaa = {FIELD: "VA NOT IDENTIFIABLE "}

    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    assert lons == []
    assert lats == []
    assert flight_level_txt == ""


# ---------------------------------------------------------------------------
# Req 3.3 - Missing field and non-string field return ([], [], "") without error
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vaa",
    [
        pytest.param({}, id="missing-field"),
        pytest.param({FIELD: 12345}, id="non-string-int"),
        pytest.param({FIELD: None}, id="non-string-none"),
        pytest.param({FIELD: ["N5825 W15450"]}, id="non-string-list"),
    ],
)
def test_missing_or_non_string_field_preserved(vaa):
    """An absent field or a non-string value returns ([], [], "") without error."""
    lons, lats, flight_level_txt = process_polygons(vaa, FIELD)

    assert lons == []
    assert lats == []
    assert flight_level_txt == ""


# ---------------------------------------------------------------------------
# Req 3.4 / 3.5 - NO VA EXP forecast field produces no coordinate pairs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field, value",
    [
        ("FCST VA CLD +6HR", "NO VA EXP"),
        ("FCST VA CLD +12HR", "NO VA EXP"),
        ("FCST VA CLD +18HR", "NO VA EXP"),
    ],
)
def test_no_va_exp_produces_no_polygons(field, value):
    """A ``NO VA EXP`` forecast field yields no polygons: ([], [], "")."""
    vaa = {field: value}

    lons, lats, flight_level_txt = process_polygons(vaa, field)

    assert lons == []
    assert lats == []
    assert flight_level_txt == ""


# ---------------------------------------------------------------------------
# Req 3.6 - text_to_latlon per-pair conversion is unchanged
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "token, expected_lat, expected_lon",
    [
        ("N5825 W15450", 58.416666666666664, -154.83333333333334),
        ("N5753 W15414", 57.88333333333333, -154.23333333333332),
    ],
)
def test_text_to_latlon_preserved(token, expected_lat, expected_lon):
    """Per-pair coordinate conversion returns the recorded baseline lat/lon."""
    lat, lon = text_to_latlon(token)

    assert lat == pytest.approx(expected_lat)
    assert lon == pytest.approx(expected_lon)
