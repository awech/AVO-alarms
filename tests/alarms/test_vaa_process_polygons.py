"""Bug condition exploration tests for VAA ``process_polygons()``.

These tests encode the EXPECTED (post-fix) behavior from Property 1 of the
``vaa-resuspended-ash-polygon-parsing`` bugfix spec. Under the NEW contract,
``process_polygons(vaa, field)`` returns a LIST of per-sub-polygon groups
``[(lons, lats, level_txt), ...]`` - one entry per parsed ring - and an EMPTY
LIST ``[]`` for empty / ``VA NOT IDENTIFIABLE`` / whole-field ``NO VA EXP`` /
missing / non-string fields.

A cloud field with valid polygon coordinates SHALL parse those coordinates and
derive ``level_txt`` for every sub-polygon ring, regardless of:

* whether either ``/``-separated level bound carries an ``FL`` prefix
  (``SFC/060``, ``060/FL200``, ``060/090``);
* a leading ``DD/HHMM`` UTC time token (``01/0858Z`` or ``01/0858``);
* multiple sub-polygons (rings) within one field;
* a trailing ``MOV <DIR> <N>KT`` motion token;
* a per-sub-polygon ``NO VA EXP`` beside a real ring.

On the UNFIXED code these tests are EXPECTED TO FAIL - the failure confirms the
bug exists:

* ``SFC/060`` / ``060/090``: the ``if "FL" in obs_text`` era gate / list
  contract is not honored (old code returns a bare tuple, not a list).
* ``060/FL200``: bare lower bound not stripped, mis-parsed as a coordinate.
* Forecast ``01/0858Z`` field: the non-greedy level regex matches the
  ``01/0858`` time token, the real level is fed into ``text_to_latlon`` ->
  ``ValueError: could not convert string to float: '-FC/060'``.
* Two-ring OBS field: the whole field is treated as one ring, so the second
  ring is dropped/merged and ``MOV ... KT`` corrupts the parse.
* Per-sub ``NO VA EXP``: whole-field ``NO VA EXP`` early-return drops the
  sibling ring / returns nothing.

The tests call ``process_polygons(vaa, field)`` directly with crafted ``vaa``
dicts - no network and no matplotlib rendering are required.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9**
"""

from __future__ import annotations

from volc_alarms.alarms.VAA.detection import process_polygons, text_to_latlon

FIELD = "OBS VA CLD"
FCST_FIELD = "FCST VA CLD +6HR"

# ---------------------------------------------------------------------------
# Original-scope single-ring fields (now wrapped in the list contract).
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Real forecast / multi-ring coordinate rings.
# ---------------------------------------------------------------------------

# Ring 1 coordinate tokens (from the spec's real example).
RING1_PAIRS = [
    "N4941 W16417",
    "N4750 W16033",
    "N4834 W15601",
    "N4941 W16417",
]
RING1_COORDS = " - ".join(RING1_PAIRS)

# Ring 2 coordinate tokens (from the spec's real example).
RING2_PAIRS = [
    "N5723 E17430",
    "N5448 W17024",
    "N5723 E17430",
]
RING2_COORDS = " - ".join(RING2_PAIRS)


def _expected_latlon(pairs):
    lats, lons = [], []
    for pr in pairs:
        lat, lon = text_to_latlon(pr)
        lats.append(lat)
        lons.append(lon)
    return lons, lats


# ===========================================================================
# Original-scope single-ring cases (list contract: single-element list).
# ===========================================================================


def test_case_a_sfc_bare_gate_mt_katmai():
    """Test case A - SFC/bare gate (MT KATMAI), single ring.

    ``SFC/060`` has no ``FL`` on either bound. The field carries 7 valid
    coordinate pairs and the level should render as ``0 - 6,000 ft``. Under the
    new contract this is a single-element list with one ring.

    UNFIXED: old code returns a bare 3-tuple, not a list; unpacking as a list
    of one group fails / the SFC/bare level yields empty coordinates.
    """
    vaa = {FIELD: MT_KATMAI_CLD}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_latlon(MT_KATMAI_PAIRS)

    assert groups == [(expected_lons, expected_lats, "0 - 6,000 ft")]


def test_case_b_mixed_bound_regex_060_fl200():
    """Test case B - mixed bound regex (``060/FL200``), single ring.

    The lower bound is bare and the upper bound carries ``FL``. The level token
    ``060/FL200`` must be stripped so it is never fed into ``text_to_latlon()``
    as a coordinate pair. Level renders as ``6,000 - 20,000 ft``.

    UNFIXED: the bare ``060`` is not stripped; the first "pair" becomes
    ``060/FL200 N5825 W15450`` which is mis-parsed, corrupting the coordinates.
    """
    field_text = (
        "060/FL200 "
        "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
        "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
    )
    vaa = {FIELD: field_text}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_latlon(MT_KATMAI_PAIRS)

    assert groups == [(expected_lons, expected_lats, "6,000 - 20,000 ft")]


def test_case_c_both_bare_060_090():
    """Test case C - both bare (``060/090``), single ring.

    Neither bound carries ``FL``. Coordinates must parse and the level should
    render as ``6,000 - 9,000 ft``.

    UNFIXED: SFC/bare-only level yields empty coordinates / bare-tuple contract.
    """
    field_text = (
        "060/090 "
        "N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - "
        "N5741 W15459 - N5818 W15524 - N5825 W15450 STNR"
    )
    vaa = {FIELD: field_text}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_latlon(MT_KATMAI_PAIRS)

    assert groups == [(expected_lons, expected_lats, "6,000 - 9,000 ft")]


# ===========================================================================
# NEW real-format bug-condition cases.
# ===========================================================================


def test_forecast_time_token_crash_with_trailing_z():
    """Forecast time-token crash (``01/0858Z``).

    A forecast field begins with a ``DD/HHMMZ`` time token before the real
    level, followed by a ``MOV ESE 70KT`` motion token, then a sibling
    sub-polygon that is ``NO VA EXP``.

    Post-fix expectation: exactly ONE ring for ``FL100/FL340`` with
    ``level_txt == "10,000 - 34,000 ft"``, the ``NO VA EXP`` sub-polygon
    skipped, and NO ``ValueError`` raised.

    UNFIXED: the non-greedy level regex matches the ``01/0858`` time token as
    the level, the real level is never stripped, and level text flows into
    ``text_to_latlon()`` -> ``ValueError: could not convert string to float:
    '-FC/060'``.
    """
    field_text = (
        "01/0858Z FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 NO VA EXP"
    )
    vaa = {FCST_FIELD: field_text}

    groups = process_polygons(vaa, FCST_FIELD)

    expected_lons, expected_lats = _expected_latlon(RING1_PAIRS)

    assert groups == [(expected_lons, expected_lats, "10,000 - 34,000 ft")]


def test_forecast_time_token_crash_without_trailing_z():
    """Forecast time-token crash without the trailing ``Z`` (``01/0858``).

    The forecast stamp appears both as ``DD/HHMMZ`` and ``DD/HHMM`` with no
    trailing ``Z``; the fix must not rely on the ``Z``. Same expectation as the
    ``Z`` variant: one ring for ``FL100/FL340``, ``NO VA EXP`` skipped, no crash.

    UNFIXED: same ``ValueError: could not convert string to float: '-FC/060'``.
    """
    field_text = (
        "01/0858 FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 NO VA EXP"
    )
    vaa = {FCST_FIELD: field_text}

    groups = process_polygons(vaa, FCST_FIELD)

    expected_lons, expected_lats = _expected_latlon(RING1_PAIRS)

    assert groups == [(expected_lons, expected_lats, "10,000 - 34,000 ft")]


def test_two_ring_obs_field():
    """Two-ring OBS field.

    A single ``OBS VA CLD`` field carries two sub-polygons, each with its own
    level bounds, its own coordinate ring, and a trailing motion token.

    Post-fix expectation: ``len(groups) == 2`` with level_txt
    ``"10,000 - 34,000 ft"`` and ``"10,000 - 28,000 ft"``.

    UNFIXED: the whole field is treated as a single ring, so the second ring is
    dropped/merged and the ``MOV ... KT`` tokens corrupt the parse.
    """
    field_text = (
        "FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 " + RING2_COORDS + " MOV SE 50KT"
    )
    vaa = {FIELD: field_text}

    groups = process_polygons(vaa, FIELD)

    expected_lons1, expected_lats1 = _expected_latlon(RING1_PAIRS)
    expected_lons2, expected_lats2 = _expected_latlon(RING2_PAIRS)

    assert len(groups) == 2
    assert groups[0] == (expected_lons1, expected_lats1, "10,000 - 34,000 ft")
    assert groups[1] == (expected_lons2, expected_lats2, "10,000 - 28,000 ft")


def test_mov_motion_token_not_parsed_as_coordinate():
    """MOV motion token must not become a coordinate.

    ``MOV ESE 70KT`` / ``MOV SE 50KT`` trail each ring and must NOT be parsed as
    coordinate pairs. Assert the parsed pair count equals the real coordinate
    count per ring, and no parsed coordinate derives from the MOV token.

    UNFIXED: the motion token is split into the coordinate run and mis-parsed
    (or crashes), so the pair counts do not match the real coordinate counts.
    """
    field_text = (
        "FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 " + RING2_COORDS + " MOV SE 50KT"
    )
    vaa = {FIELD: field_text}

    groups = process_polygons(vaa, FIELD)

    assert len(groups) == 2

    # Ring 1: exactly the real coordinate count (4 pairs), MOV excluded.
    lons1, lats1, _ = groups[0]
    assert len(lons1) == len(lats1) == len(RING1_PAIRS)
    expected_lons1, expected_lats1 = _expected_latlon(RING1_PAIRS)
    assert lons1 == expected_lons1
    assert lats1 == expected_lats1

    # Ring 2: exactly the real coordinate count (3 pairs), MOV excluded.
    lons2, lats2, _ = groups[1]
    assert len(lons2) == len(lats2) == len(RING2_PAIRS)
    expected_lons2, expected_lats2 = _expected_latlon(RING2_PAIRS)
    assert lons2 == expected_lons2
    assert lats2 == expected_lats2

    # The MOV token direction ("ESE"/"SE") and speed ("70KT"/"50KT") must never
    # appear among the parsed coordinates - verified by exact equality above and
    # by the pair count matching the real coordinate count.


def test_per_sub_polygon_no_va_exp_beside_real_ring():
    """Per-sub-polygon ``NO VA EXP`` beside a real ring.

    A ``FL100/FL280 NO VA EXP`` sub-polygon sits beside a real ring. Only the
    real ring must be returned, with no crash.

    Post-fix expectation: exactly one ring for ``FL100/FL340``
    (``10,000 - 34,000 ft``); the ``NO VA EXP`` sibling yields no ring.

    UNFIXED: the whole-field ``NO VA EXP`` early-return path fires (or the real
    ring is dropped), so the real ring is lost.
    """
    field_text = (
        "FL100/FL340 " + RING1_COORDS + " MOV ESE 70KT\n"
        "FL100/FL280 NO VA EXP"
    )
    vaa = {FIELD: field_text}

    groups = process_polygons(vaa, FIELD)

    expected_lons, expected_lats = _expected_latlon(RING1_PAIRS)

    assert groups == [(expected_lons, expected_lats, "10,000 - 34,000 ft")]
