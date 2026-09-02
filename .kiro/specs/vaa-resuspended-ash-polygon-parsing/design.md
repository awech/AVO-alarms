# VAA Resuspended-Ash Polygon Parsing Bugfix Design

## Overview

`process_polygons()` in `src/volc_alarms/alarms/VAA/detection.py` extracts polygon
coordinates and a flight-level label from a VAA cloud field (e.g. `OBS VA CLD`,
`FCST VA CLD +6HR`). A cloud level is two `/`-separated bounds (lower/upper ash
altitude); each bound can be `FLxxx`, a bare `xxx`, or `SFC`.

The spec originally covered a single failure mode - the code assumed the `FL`
prefix was always present. A NEW real-world failure has since been found that the
single-polygon model does not cover. The production command
`run-alarm --test -t 202609010000 VAA` crashed with
`ValueError: could not convert string to float: '-FC/060'` inside `text_to_latlon`,
called from `process_polygons(vaa, "FCST VA CLD +6HR")`. Forecast cloud fields use
a richer format than the OBS examples the spec was built on:

1. **Leading `DD/HHMM` time token.** Forecast fields begin with a `DD/HHMM` UTC
   time token, e.g. `01/0858Z` or `01/0858` (the trailing `Z` is not always present), BEFORE the level. Because that token is itself
   `digits/digits`, the non-greedy level regex
   `.*?(?:FL\d+|SFC|\d+)/(?:FL\d+|SFC|\d+)` matches the TIME token (`01/0858`)
   instead of the real level (`FL100/FL340`). The real level is never stripped, and
   level text is fed into `text_to_latlon()` -> the `-FC/060` `ValueError`. (OBS
   fields may have NO time token, or a full `YYYYMMDD/HHMMZ`. The forecast
   stamp appears both as `DD/HHMMZ` and `DD/HHMM` with no trailing `Z`.)
2. **Multiple sub-polygons per field.** A single cloud field can contain MULTIPLE
   sub-polygons, each with its OWN level bounds and its OWN coordinate ring,
   separated by newlines. The current single-ring model drops or merges the later
   rings.
3. **Trailing motion tokens.** `MOV <DIR> <N>KT` (e.g. `MOV ESE 70KT`) trails the
   last coordinate of a ring and must NOT be parsed as a coordinate.
4. **Per-sub-polygon `NO VA EXP`.** A sub-polygon can be `NO VA EXP` (e.g.
   `FL100/FL280 NO VA EXP`) even when a sibling ring in the same field has real
   coordinates; it must be skipped without dropping the sibling.
5. **Newline-wrapped coordinates.** `N4941 W16417` may wrap across a newline
   (`N4941`\n`W16417`); the existing newline-to-space normalization handles this and
   must be preserved.

To support multiple rings, the `process_polygons()` return contract CHANGES from a
single `(lons, lats, flight_level_txt)` tuple to a LIST of per-sub-polygon groups
`[(lons, lats, level_txt), ...]`, one entry per parsed ring (empty list for
empty / `VA NOT IDENTIFIABLE` / whole-field `NO VA EXP` / missing / non-string).
`make_map()` in `figure.py` iterates the list and plots each ring as its own line,
one legend entry per field, and shows all distinct OBS levels comma-separated in the
title. `text_to_latlon()` and `get_extent()` are unchanged.

## Glossary

- **Bug_Condition (C)**: The field exists, is a string, is not `VA NOT IDENTIFIABLE`
  or a whole-field `NO VA EXP`, contains at least one valid ring, and exhibits at
  least one real-format feature the current code mishandles: a bound without `FL`, a
  leading `DD/HHMM` time token, multiple sub-polygons, a trailing `MOV ... KT`
  motion token, or a per-sub-polygon `NO VA EXP`.
- **Property (P)**: For a bug-condition input, `process_polygons()` returns one
  `(lons, lats, level_txt)` group per parsed ring, with the level token, leading
  time token, and trailing motion tokens excluded from coordinates, and level text
  computed per bound (`SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` -> `xxx*100`).
- **Preservation**: Single-ring `FL`-prefixed levels (modulo the new list wrapping),
  `VA NOT IDENTIFIABLE`, whole-field `NO VA EXP`, missing/non-string fields, per-pair
  `text_to_latlon()` conversion, and the global `No polygons to plot` path behave as
  before.
- **process_polygons**: The function in `detection.py` that turns a cloud field
  string into a list of `(lons, lats, level_txt)` groups (previously a single tuple).
- **make_map**: The function in `figure.py` that renders the advisory figure. It now
  iterates the per-field group list, plots each ring, and builds a multi-level title.
- **text_to_latlon**: The helper that converts one `Nxxxx Wxxxxx` token into
  `(lat, lon)`. Unchanged by this fix.
- **get_extent**: The map-extent helper. Unchanged by this fix.
- **level token**: A `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair immediately
  followed by whitespace and a coordinate token (`[NS]\d`). This context requirement
  distinguishes the real level from the leading `DD/HHMM` time token (which is
  followed by the level, NOT a coordinate; the trailing `Z` may be absent, so the
  `Z` must NOT be relied on) and from digit runs inside coordinates.
- **time token**: The leading UTC stamp on a forecast field, appearing as
  `DD/HHMMZ` or `DD/HHMM` (no trailing `Z`), or a full `YYYYMMDD/HHMMZ`, e.g.
  `01/0858Z` or `01/0858`, preceding the level.
- **motion token**: A trailing `MOV <DIR> <N>KT`, e.g. `MOV ESE 70KT`.
- **sub-polygon / ring**: One level + one coordinate ring within a field. A field may
  hold several, newline-separated.
- **bound**: One of the two `/`-separated altitude values. Forms: `FLxxx`, bare
  `xxx`, or `SFC`.

## Bug Details

### Bug Condition

The bug manifests when a forecast field carries a leading `DD/HHMM` time token, when
a field carries more than one sub-polygon, motion tokens, or a per-sub-polygon
`NO VA EXP`, or (original scope) when a level bound lacks the `FL` prefix. The code
either matches the time token as the level (crashing in `text_to_latlon`), drops or
merges later rings, mis-parses `MOV ... KT` as coordinates, crashes on a
per-sub-polygon `NO VA EXP`, or (original) skips parsing / mis-strips the level.

**Formal Specification:**
```
FUNCTION isBugCondition(vaa, field)
  INPUT: vaa (parsed advisory dict), field (cloud field name)
  OUTPUT: boolean

  RETURN field IN vaa
         AND isString(vaa[field])
         AND NOT contains(vaa[field], "VA NOT IDENTIFIABLE ")
         AND NOT isWholeFieldNoVaExp(vaa[field])
         AND hasAtLeastOneValidRing(vaa[field])
         AND ( levelHasBoundWithoutFLPrefix(vaa[field])
            OR hasLeadingTimeToken(vaa[field])
            OR hasMultipleSubPolygons(vaa[field])
            OR hasMotionToken(vaa[field])
            OR hasPerSubPolygonNoVaExp(vaa[field]) )
END FUNCTION
```

A level is recognized ONLY at a `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair
immediately followed by whitespace and a coordinate token (`[NS]\d`).

### Examples

Real production two-ring OBS field (`OBS VA CLD`):
```
FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT
FL100/FL280 N5723 E17430 - ... - N5723 E17430 MOV SE 50KT
```
- Expected: two rings; ring 1 level `10,000 - 34,000 ft`, ring 2 level
  `10,000 - 28,000 ft`; `MOV ESE 70KT` / `MOV SE 50KT` NOT parsed as coordinates.
- Actual (unfixed): the whole field is treated as a single ring, so the second ring
  is dropped/merged and the `MOV ... KT` tokens corrupt the parse.

Real production forecast field that crashed (`FCST VA CLD +6HR`):
```
01/0858Z FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT
FL100/FL280 NO VA EXP
```
- Expected: skip the `01/0858Z` time token; one ring for `FL100/FL340`
  (`10,000 - 34,000 ft`); skip the `FL100/FL280 NO VA EXP` sub-polygon; no crash.
- Actual (unfixed): the non-greedy regex matches `01/0858` as the level, the real
  level is never stripped, and level text flows into `text_to_latlon()` ->
  `ValueError: could not convert string to float: '-FC/060'` (the observed crash).

Original-scope single-ring examples (still covered):
- `SFC/060 N5825 W15450 - ... - N5825 W15450 STNR` (MT KATMAI): one ring, 7 pairs,
  level `0 - 6,000 ft`.
- `060/FL200 N... - N...`: level token stripped, coordinates clean, level
  `6,000 - 20,000 ft`.
- `060/090 N... - N...`: coordinates parsed, level `6,000 - 9,000 ft`.
- `SFC/FL060 N... - N...`: unchanged single-ring FL behavior.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Single-ring `FL`-prefixed levels (`SFC/FL060`, `FL200/FL300`) SHALL parse the same
  coordinates and level text as before, wrapped as a single-element list (Req 3.1).
- A field containing `VA NOT IDENTIFIABLE ` SHALL produce an empty list (Req 3.2).
- An absent or non-string field SHALL produce an empty list without error (Req 3.3).
- A whole-field `NO VA EXP` forecast field SHALL produce an empty list (Req 3.4).
- An advisory with genuinely no valid coordinates SHALL still cause `make_map()` to
  log `No polygons to plot. Not generating figure.` and skip the figure (Req 3.5).
- `text_to_latlon()` SHALL produce the same lat/lon values as before (Req 3.6).
- Newline-wrapped coordinates within a ring SHALL still join correctly (Req 3.7).

**Scope:**
Inputs that do NOT satisfy the bug condition must be unaffected: single-ring
`FL`-prefixed fields, `VA NOT IDENTIFIABLE`, whole-field `NO VA EXP`, missing and
non-string fields, and the per-pair conversion path in `text_to_latlon()`.

**Note:** The expected correct behavior for bug-condition inputs is defined in the
Correctness Properties section (Property 1).

## Hypothesized Root Cause

The failures stem from two root assumptions in `process_polygons()`, plus the
original `FL`-prefix assumption:

1. **Single-polygon model.** The function assumes one field carries one level and
   one coordinate ring. Real fields (especially forecasts) carry MULTIPLE
   sub-polygons separated by newlines, each with its own level and ring. Because the
   remainder after stripping one level is split on `" - "` as a single ring, later
   rings are dropped or merged, and later level tokens are consumed as coordinates.

2. **Level regex matches the leading time token.** The regex
   `.*?(?:FL\d+|SFC|\d+)/(?:FL\d+|SFC|\d+)` is non-greedy and has no context guard,
   so on a forecast field beginning with `01/0858Z` it matches the `01/0858`
   `digits/digits` time token as the level. The real level (`FL100/FL340`) is left in
   the coordinate text and later fed to `text_to_latlon()`, raising
   `ValueError: could not convert string to float: '-FC/060'`. The fix requires the
   level to be immediately followed by whitespace and a coordinate token (`[NS]\d`),
   which the time token does not satisfy (it is followed by the level). The trailing
   `Z` is NOT relied on, since the stamp may appear as `DD/HHMM` with no `Z`.

3. **No motion-token / per-sub `NO VA EXP` handling.** `MOV <DIR> <N>KT` trailing a
   ring is not stripped and is parsed as a coordinate; a `NO VA EXP` sub-polygon
   inside a multi-ring field is not skipped, crashing or dropping the sibling.

4. **`FL`-prefix assumptions (original scope).** A bare bound (`060`) mapped to
   `np.nan` (suppressing level text) and levels lacking any `FL` were dropped by the
   old `FL`-anchored regex / gate. Retained in this design for completeness; the
   per-bound altitude helper still applies.

## Correctness Properties

Property 1: Bug Condition - Real-Format Cloud Fields Parse Every Ring

_For any_ input where the bug condition holds (isBugCondition returns true), the
fixed `process_polygons` SHALL return a list containing one `(lons, lats, level_txt)`
group per parsed ring, where each ring's `lons`/`lats` are non-empty, equal-length,
and equal to that ring's coordinates with the level token, the leading `DD/HHMM` time
token, and any trailing `MOV ... KT` motion tokens excluded; `level_txt` is computed
per bound via `SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` -> `xxx*100` (else `""` for
that ring). A per-sub-polygon `NO VA EXP` yields no group but does not drop siblings.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9**

Property 2: Preservation - Single-Ring FL and Non-Coordinate Cases Unchanged

_For any_ input where the bug condition does NOT hold (isBugCondition returns false),
the fixed `process_polygons` SHALL produce results equivalent to the original: a
single-ring `FL`-prefixed field yields a single-element list whose one group equals
the original `(lons, lats, level_txt)` tuple; `VA NOT IDENTIFIABLE`, whole-field
`NO VA EXP`, missing, and non-string fields yield an empty list. `text_to_latlon()`
and the global `No polygons to plot` path are unchanged.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

## Fix Implementation

### Changes Required

The fix touches `process_polygons()` in `detection.py` (new list contract, segment
splitting, time/MOV stripping) and `make_map()` in `figure.py` (iterate + per-ring
plot, single legend per field, multi-level title). `text_to_latlon()` and
`get_extent()` are unchanged.

**File**: `src/volc_alarms/alarms/VAA/detection.py`

**Function**: `process_polygons(vaa, field)`

**Specific Changes**:

1. **New return contract**: Return a LIST of `(lons, lats, level_txt)` groups, one
   per parsed ring. Keep the existing early-returns (missing field, non-string,
   `VA NOT IDENTIFIABLE`, whole-field `NO VA EXP`) but have them `return []` under
   the new contract. Preserve the newline-to-space normalization first.

2. **Context-guarded level detection**: Recognize a level ONLY where a
   `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair is immediately followed by whitespace
   and a coordinate token (`[NS]\d`), e.g.:
   ```
   level_at = re.compile(r"(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)(?=\s+[NS]\d)")
   ```
   This distinguishes the real level from a leading `DD/HHMM` time token (which is
   followed by the level, not a coordinate) and from digit runs inside coordinates.
   The trailing `Z` is NOT relied on: the stamp may be `DD/HHMMZ` or `DD/HHMM`.

3. **Segment splitting**: Split the field into sub-polygon segments at each level-token
   boundary (e.g. iterate the matches of `level_at`; each segment spans from one
   level token to the next level token / end of field). For each segment, capture the
   two level bounds and the coordinate run.

4. **Strip time and motion tokens**: Before per-pair `text_to_latlon()`, strip any
   leading time token(s) (matched, not consumed, by the level guard) and any trailing
   `MOV ... KT` motion token from each segment's coordinate run, e.g.:
   ```
   coords = re.sub(r"\s*MOV\s+\S+\s+\d+KT.*$", "", segment_coords).strip()
   ```
   Then split the remaining run on `" - "` and convert each pair.

5. **Per-sub-polygon `NO VA EXP`**: If a segment's coordinate run has no coordinate
   token (e.g. `FL100/FL280 NO VA EXP`), yield no group for that segment and continue
   to the next sibling without error.

6. **Per-bound altitude mapping (unchanged rule)**: `SFC` -> 0, `FLxxx` ->
   `float(xxx)*100`, bare all-digit `xxx` -> `float(xxx)*100`, else `np.nan`. Emit a
   ring's `level_txt` only when both bounds resolve to non-NaN
   (`flight_levels.size == 2 and not np.isnan(flight_levels).any()`), formatting as
   `f"{lo:,g} - {hi:,g} ft"` (so `FL100/FL340` -> `10,000 - 34,000 ft`, `SFC/060` ->
   `0 - 6,000 ft`). A ring with an unparseable bound still returns its coordinates
   with `level_txt == ""`.

**File**: `src/volc_alarms/alarms/VAA/figure.py`

**Function**: `make_map(vaa, config, test=False)`

**Specific Changes**:

1. **Consume the list contract**: For each field call
   `groups = process_polygons(vaa, field)` and gather all rings' coordinates for the
   `LONS`/`LATS` concatenation and `get_extent()` (unchanged extent logic on the
   union of all coordinates).

2. **Plot each ring separately**: Iterate a field's groups and plot each ring as its
   OWN `ax.plot(...)` line, so there is no spurious connecting segment between
   distinct rings. Apply that field's existing style to each of its rings:
   - OBS (`OBS VA CLD`): firebrick, solid, lw 1.5, zorder 100
   - +6H (`FCST VA CLD +6HR`): orangered, dashed, lw 1.25, zorder 99
   - +12H (`FCST VA CLD +12HR`): orange, dashed, lw 1, zorder 98
   - +18H (`FCST VA CLD +18HR`): goldenrod, dash-dot, lw 0.75, zorder 97

3. **Single legend entry per field**: Label only the FIRST ring of each field with
   the field's legend label; subsequent rings of the same field use
   `label='_nolegend_'` so the legend shows one entry per field.

4. **Multi-level title**: Collect all DISTINCT OBS `level_txt` values (in order,
   deduplicated) and join them comma-separated (e.g.
   `10,000 - 34,000 ft, 10,000 - 28,000 ft`). Keep the title format
   `f"{volcano_name} VAA\n{levels}\n{vaa_time}"`.

5. **No-polygons path unchanged**: When NO rings exist across every field
   (all group lists empty), still log
   `No polygons to plot. Not generating figure.` and return `[]` (Req 3.5).

## Testing Strategy

### Validation Approach

Two phases: surface counterexamples on the UNFIXED code, then verify the fix parses
every ring and preserves the unchanged cases. Because the return contract changes to
a list, the existing tests
(`tests/alarms/test_vaa_process_polygons.py`,
`tests/alarms/test_vaa_process_polygons_preservation.py`,
`tests/alarms/test_vaa_make_map.py`) assume the OLD single-tuple contract and MUST be
revised to the new list-based contract. Tests call `process_polygons()` /
`make_map()` directly with crafted `vaa` dicts (no network); `make_map` avoids disk
side effects by mocking `figure.plotting.save_file`.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE the fix and confirm
the root cause. If a test unexpectedly passes on unfixed code, re-hypothesize.

**Test Plan**: Call `process_polygons()` with crafted fields for each new real-format
feature and assert on the returned list. Run on UNFIXED code first.

**Test Cases**:
1. **Forecast time-token crash (`01/0858Z`)**: `FCST VA CLD +6HR` =
   `01/0858Z FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT` then newline
   `FL100/FL280 NO VA EXP` -> on unfixed code raises
   `ValueError: could not convert string to float: '-FC/060'`. Expected after fix:
   one ring `10,000 - 34,000 ft`, `NO VA EXP` sub-polygon skipped, no crash.
2. **Two-ring OBS field**: `FL100/FL340 ... MOV ESE 70KT` /
   `FL100/FL280 ... MOV SE 50KT` -> expect two rings with levels `10,000 - 34,000 ft`
   and `10,000 - 28,000 ft` (will fail on unfixed code: single/merged ring).
3. **MOV motion token**: assert `MOV ESE 70KT` / `MOV SE 50KT` are NOT among parsed
   coordinates (will fail on unfixed code: mis-parsed as a pair).
4. **Per-sub-polygon `NO VA EXP`**: `FL100/FL280 NO VA EXP` beside a real ring ->
   only the real ring returned, no crash (will fail on unfixed code).
5. **Original scope**: MT KATMAI `SFC/060 ...` -> one ring, 7 pairs, `0 - 6,000 ft`;
   `060/FL200` and `060/090` (will fail on unfixed code).

**Expected Counterexamples**:
- `ValueError: could not convert string to float: '-FC/060'` on the forecast field.
- Second ring dropped/merged for the two-ring OBS field; `MOV ... KT` in coordinates.
- Possible causes: single-polygon model, time-token regex match, no MOV / per-sub
  `NO VA EXP` handling.

### Fix Checking

**Goal**: For all bug-condition inputs the fixed function returns one group per ring.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  groups := process_polygons_fixed(input.vaa, input.field)
  ASSERT length(groups) == numberOfValidRings(input.field)
  FOR EACH (lons, lats, level_txt) IN groups DO
    ASSERT length(lons) > 0 AND length(lons) == length(lats)
    ASSERT lons, lats EQUAL that ring's coordinates
           (level, DD/HHMM time token, MOV ... KT excluded)
    ASSERT level_txt via SFC -> 0, FLxxx -> xxx*100, bare xxx -> xxx*100
  END FOR
END FOR
```

### Preservation Checking

**Goal**: For all non-bug-condition inputs the fixed function is equivalent to the
original (modulo list wrapping).

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  groups := process_polygons_fixed(input.vaa, input.field)
  IF single-ring FL-prefixed THEN
    ASSERT groups == [ original_tuple(input) ]
  ELSE
    ASSERT groups == []
  END IF
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation because
it generates many inputs, catches edge cases, and gives strong "for all non-buggy
inputs" assurance. (If `hypothesis` is unavailable, enumerate representative
parametrized examples following the observation-first methodology.)

**Test Plan**: Record UNFIXED behavior for single-ring `FL`-prefixed levels,
`VA NOT IDENTIFIABLE`, whole-field `NO VA EXP`, missing/non-string fields, and
`text_to_latlon()`, then assert the fixed list output wraps/matches those baselines.

**Test Cases**:
1. **Single-ring FL preservation**: `SFC/FL060` and `FL200/FL300` yield a
   single-element list whose group equals the recorded coordinates and level text.
2. **VA NOT IDENTIFIABLE**: returns `[]`.
3. **Missing / non-string field**: returns `[]` without error.
4. **Whole-field NO VA EXP**: returns `[]`.
5. **text_to_latlon**: per-pair conversion returns the same recorded lat/lon.
6. **Newline-wrapped coordinates**: still join correctly.

### Unit Tests

- `process_polygons()` for each real-format feature: forecast `01/0858Z` time token,
  two-ring OBS field, `MOV ... KT` stripping, per-sub `NO VA EXP`, and original
  `SFC/060` / `060/FL200` / `060/090` / `SFC/FL060` / `FL200/FL300`.
- Level-text mapping and `10,000 - 34,000 ft` / `0 - 6,000 ft` formatting.
- Non-coordinate cases returning `[]`.

### Property-Based Tests

- Generate fields with N rings (each a random level from `{SFC, FLxxx, xxx}` bounds
  plus a random valid coordinate polygon, optional leading time token and trailing
  `MOV ... KT`); assert `len(groups) == N` and each ring's coordinates/level match
  (Property 1).
- Generate single-ring `FL`-prefixed and non-coordinate inputs; assert the fixed list
  output wraps/matches the original (Property 2).

### Integration Tests

- Feed the user's real two-ring OBS field plus the `01/0858Z` forecast field through
  `make_map()` (mocking `save_file`); assert a figure IS generated, each ring is a
  separate plotted line, the legend has one entry per field, and the title lists all
  distinct OBS levels comma-separated (`10,000 - 34,000 ft, 10,000 - 28,000 ft`).
- Confirm a genuine no-coordinate advisory still logs
  `No polygons to plot. Not generating figure.` and skips the figure (Req 3.5).
