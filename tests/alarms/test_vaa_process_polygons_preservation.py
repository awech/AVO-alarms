r"""Preservation tests for VAA ``process_polygons()`` (Property 2).

These tests capture the BASELINE behavior of ``process_polygons()`` that the
``vaa-resuspended-ash-polygon-parsing`` bugfix MUST NOT change (Property 2,
Requirements 3.1-3.4, 3.6, 3.7). They cover the inputs where the bug condition
does NOT hold: single-ring ``FL``-prefixed levels, ``VA NOT IDENTIFIABLE``,
whole-field ``NO VA EXP``, missing / non-string fields, newline-wrapped
coordinates, and the per-pair ``text_to_latlon()`` conversion.

New list contract
-----------------
The bugfix CHANGES the ``process_polygons()`` return contract from a single
``(lons, lats, flight_level_txt)`` tuple to a LIST of per-sub-polygon groups
``[(lons, lats, level_txt), ...]`` (one entry per parsed ring), returning an
EMPTY LIST ``[]`` for empty / ``VA NOT IDENTIFIABLE`` / whole-field
``NO VA EXP`` / missing / non-string fields. These preservation tests are
written to that NEW contract.

Observation-first methodology
-----------------------------
The expected values asserted below were recorded by running the UNFIXED
``process_polygons()`` / ``text_to_latlon()`` and copying their actual outputs.
Under the OLD contract the unfixed code returned:

* ``SFC/FL060 <coords>``   -> (lons, lats, "0 - 6,000 ft")      [bare tuple]
* ``FL200/FL300 <coords>`` -> (lons, lats, "20,000 - 30,000 ft")[bare tuple]
* ``"VA NOT IDENTIFIABLE "`` -> ([], [], "")
* missing field            -> ([], [], "")  (no error)
* non-string field value   -> ([], [], "")  (no error)
* ``FCST VA CLD +6HR`` == "NO VA EXP" -> ([], [], "")
* newline-wrapped coords    -> coordinates joined and parsed (bare tuple)
* text_to_latlon("N5825 W15450") -> (58.416666666666664, -154.83333333333334)
* text_to_latlon("N5753 W15414") -> (57.88333333333333, -154.23333333333332)

Baseline -> new-contract mapping (documented per Task 2):

* The single-ring FL bare tuple ``(lons, lats, level_txt)`` becomes a
  single-element list ``[(lons, lats, level_txt)]`` after the fix.
* The non-coordinate empty tuple ``([], [], "")`` becomes ``[]`` after the fix.

Post-fix vs unfixed expectations
--------------------------------
* The single-ring FL list-wrapping assertions
  (``test_single_ring_fl_prefixed_wraps_to_single_element_list``) encode the
  POST-FIX preservation contract. They are EXPECTED TO FAIL on the UNFIXED code
  (which returns a bare tuple, not a one-element list) and are validated after
  the fix in Task 3.5.
* The non-coordinate ``== []`` assertions also expect the NEW contract; on the
  UNFIXED code these return ``([], [], "")`` (not ``[]``), so they too only pass
  post-fix. The recorded empty-tuple baseline maps to ``[]``.
* ``test_text_to_latlon_preserved`` is unchanged by the fix and passes on both
  the unfixed and fixed code.

Note on tooling
---------------
The bugfix spec calls for property-based generation of the preservation cases,
but ``hypothesis`` is not installed in the ``dev-alarms`` environment. These
tests therefore use ``pytest`` parametrized fixed examples that enumerate the
representative baseline inputs instead of randomized generation. The assertions
still follow the observation-first methodology (recorded actual outputs).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 3.7**
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
# Req 3.1 / 3.7 - Single-ring FL-prefixed levels parse the same coordinates and
# level text as before, wrapped as a single-element list (NEW contract).
#
# POST-FIX CONTRACT: these list-wrapping assertions only pass AFTER the fix
# wraps the (lons, lats, level_txt) tuple in a list. On the UNFIXED code
# process_polygons() returns a bare tuple, so these are EXPECTED TO FAIL until
# Task 3.1 lands and are re-verified in Task 3.5.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "level, expected_level_txt",
    [
        ("SFC/FL060", "0 - 6,000 ft"),
        ("FL200/FL300", "20,000 - 30,000 ft"),
    ],
)
def test_single_ring_fl_prefixed_wraps_to_single_element_list(
    level, expected_level_txt
):
    """Single-ring FL-prefixed level: one group equal to the recorded baseline.

    Baseline (unfixed, bare tuple): 7 coordinate pairs and the recorded level
    text. NEW contract: ``groups == [(lons, lats, level_txt)]``.
    """
    vaa = {FIELD: f"{level} {COORDS}"}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_lons_lats(COORD_PAIRS)

    # Single ring -> single-element list under the new contract.
    assert isinstance(groups, list)
    assert len(groups) == 1

    lons, lats, level_txt = groups[0]
    assert len(lons) == len(lats) == 7
    assert lons == expected_lons
    assert lats == expected_lats
    assert level_txt == expected_level_txt

    # Explicit whole-group equality (the recorded baseline, wrapped as a list).
    assert groups == [(expected_lons, expected_lats, expected_level_txt)]


# ---------------------------------------------------------------------------
# Req 3.7 - Newline-wrapped coordinates within a ring still join and parse.
#
# One coordinate pair is split across a newline (``N5825``\n``W15450``); the
# existing newline-to-space normalization must join it back so the ring still
# parses. POST-FIX CONTRACT: wrapped in a single-element list.
# ---------------------------------------------------------------------------
def test_newline_wrapped_coordinates_join_within_ring():
    """A coordinate pair split across a newline still joins and parses (Req 3.7).

    Baseline (unfixed): the wrapped pair joins to 3 coordinate pairs with level
    text ``0 - 6,000 ft``. NEW contract: a single-element list.
    """
    field_value = "SFC/FL060 N5825\nW15450 - N5753 W15414 - N5825 W15450 STNR"
    vaa = {FIELD: field_value}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_lons_lats(
        ["N5825 W15450", "N5753 W15414", "N5825 W15450 STNR"]
    )

    assert isinstance(groups, list)
    assert len(groups) == 1

    lons, lats, level_txt = groups[0]
    assert len(lons) == len(lats) == 3
    assert lons == expected_lons
    assert lats == expected_lats
    assert level_txt == "0 - 6,000 ft"


# ---------------------------------------------------------------------------
# Req 3.2 - VA NOT IDENTIFIABLE returns an empty list.
#
# Baseline (unfixed) returned ([], [], "") -> maps to [] under the new contract.
# ---------------------------------------------------------------------------
def test_va_not_identifiable_returns_empty_list():
    """A ``VA NOT IDENTIFIABLE `` field returns ``[]`` (was ``([], [], "")``)."""
    vaa = {FIELD: "VA NOT IDENTIFIABLE "}

    groups = process_polygons(vaa, FIELD)

    assert groups == []


# ---------------------------------------------------------------------------
# Req 3.3 - Missing field and non-string field return [] without error.
#
# Baseline (unfixed) returned ([], [], "") -> maps to [] under the new contract.
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
def test_missing_or_non_string_field_returns_empty_list(vaa):
    """An absent field or a non-string value returns ``[]`` without error."""
    groups = process_polygons(vaa, FIELD)

    assert groups == []


# ---------------------------------------------------------------------------
# Req 3.4 - Whole-field NO VA EXP forecast field returns an empty list.
#
# Baseline (unfixed) returned ([], [], "") -> maps to [] under the new contract.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "field",
    [
        "FCST VA CLD +6HR",
        "FCST VA CLD +12HR",
        "FCST VA CLD +18HR",
    ],
)
def test_whole_field_no_va_exp_returns_empty_list(field):
    """A whole-field ``NO VA EXP`` forecast field yields ``[]``."""
    vaa = {field: "NO VA EXP"}

    groups = process_polygons(vaa, field)

    assert groups == []


# ---------------------------------------------------------------------------
# Req 3.6 - text_to_latlon per-pair conversion is unchanged (passes on both the
# unfixed and fixed code; text_to_latlon is not modified by this fix).
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
