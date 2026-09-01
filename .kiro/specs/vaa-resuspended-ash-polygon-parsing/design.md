# VAA Resuspended-Ash Polygon Parsing Bugfix Design

## Overview

`process_polygons()` in `src/volc_alarms/alarms/VAA/detection.py` extracts polygon
coordinates and a flight-level label from a VAA cloud field (e.g. `OBS VA CLD`). A
cloud level is expressed as two `/`-separated bounds (lower/upper ash altitude),
and each bound can independently be `FLxxx`, a bare `xxx`, or `SFC`.

The current implementation assumes the `FL` prefix is always present. This single
wrong assumption produces three defects that share one root cause:

1. All coordinate parsing is gated behind `if "FL" in obs_text:`, so a level with no
   `FL` prefix on either bound (e.g. `SFC/060`) skips parsing entirely and returns
   empty coordinate lists. `make_map()` then logs `No polygons to plot. Not
   generating figure.` and drops a valid detection.
2. The level-token regex `r".*\S+/FL\S+"` requires `FL` after the `/`, so mixed or
   bare levels (`060/FL200`, `060/090`) never match. The unstripped level token is
   then fed to `text_to_latlon()` as a coordinate pair, corrupting the parse.
3. The per-bound height mapping sends a bare `060` into `else: height = np.nan`,
   suppressing the level text even when the level is valid.

The fix decouples coordinate parsing from the presence of `FL`, recognizes and
strips the leading time/level token for every combination of bound forms, and
computes altitude per bound (`SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` ->
`xxx*100`). The change is targeted: a more robust level-token regex plus a
per-bound altitude helper, with the coordinate-parsing block hoisted out from
under the `FL` gate. All existing behavior for `FL`-prefixed advisories,
`VA NOT IDENTIFIABLE`, `NO VA EXP`, missing/non-string fields, and per-pair
`text_to_latlon()` conversion is preserved.

## Glossary

- **Bug_Condition (C)**: The field exists, is a string, is not a `VA NOT
  IDENTIFIABLE` case, contains valid polygon coordinates, and at least one of the
  two `/`-separated level bounds lacks an `FL` prefix (is `SFC` or a bare number).
- **Property (P)**: For a bug-condition input, `process_polygons()` returns the
  full set of parsed coordinates (level token excluded) and computes the level
  text using `SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` -> `xxx*100`.
- **Preservation**: `FL`-prefixed levels, non-coordinate cases (`VA NOT
  IDENTIFIABLE`, `NO VA EXP`, missing/non-string fields), and per-pair
  `text_to_latlon()` conversion behave exactly as before.
- **process_polygons**: The function in `src/volc_alarms/alarms/VAA/detection.py`
  that turns a cloud field string into `(lons, lats, flight_level_txt)`.
- **text_to_latlon**: The helper in the same file that converts one `Nxxxx Wxxxxx`
  coordinate token into `(lat, lon)` degrees. It is not modified by this fix.
- **level token / time_and_level**: The leading portion of the cloud field that
  carries the observation time and the `lower/upper` level, e.g. `SFC/060` or
  `20250101/0000Z SFC/FL060`, preceding the first coordinate pair.
- **bound**: One of the two `/`-separated altitude values in a level. Forms:
  `FLxxx`, bare `xxx`, or `SFC`.

## Bug Details

### Bug Condition

The bug manifests when a cloud field carries valid polygon coordinates but at least
one of the two `/`-separated level bounds lacks an `FL` prefix. Depending on the
combination, the code either skips coordinate parsing entirely (gate defect), fails
to strip the level token so it is mis-parsed as a coordinate (regex defect), or maps
a valid bare bound to `np.nan` and suppresses the level text (height-mapping defect).

**Formal Specification:**
```
FUNCTION isBugCondition(vaa, field)
  INPUT: vaa (parsed advisory dict), field (cloud field name, e.g. "OBS VA CLD")
  OUTPUT: boolean

  RETURN field IN vaa
         AND isString(vaa[field])
         AND NOT contains(vaa[field], "VA NOT IDENTIFIABLE ")
         AND hasValidCoordinates(vaa[field])
         AND levelHasBoundWithoutFLPrefix(vaa[field])
END FUNCTION
```

Where `levelHasBoundWithoutFLPrefix` is true when either `/`-separated bound of the
level is `SFC` or a bare number (no `FL`).

### Examples

- `SFC/060 N5825 W15450 - ... - N5825 W15450 STNR` (MT KATMAI `OBS VA CLD`):
  expected 7 coordinate pairs and level text `0 - 6,000 ft`; actual returns empty
  lists (gate defect), no figure generated.
- `060/FL200 N... - N...`: expected level token stripped and coordinates parsed;
  actual the regex fails, `060/FL200 N...` is passed to `text_to_latlon()` as the
  first pair, corrupting coordinates.
- `060/090 N... - N...`: expected level text `6,000 - 9,000 ft`; actual gate is
  skipped (no `FL` substring), empty lists returned.
- `SFC/FL060 N... - N...` (edge, `FL` present on upper bound): expected unchanged
  behavior; today this happens to work because the `FL` substring is present and
  the regex matches. Must remain correct after the fix.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `FL`-prefixed levels (e.g. `SFC/FL060`, `FL200/FL300`) SHALL parse coordinates and
  derive level text exactly as before (Req 3.1).
- A field containing `VA NOT IDENTIFIABLE ` SHALL return empty coordinate lists and
  skip the field (Req 3.2).
- A field that is absent or not a string SHALL return empty coordinate lists without
  error (Req 3.3).
- A forecast field indicating `NO VA EXP` SHALL produce no polygons (Req 3.4).
- An advisory with genuinely no valid coordinates SHALL still cause `make_map()` to
  log `No polygons to plot. Not generating figure.` and skip figure generation (Req
  3.5).
- `text_to_latlon()` SHALL produce the same lat/lon values as before for each
  coordinate pair (Req 3.6).

**Scope:**
All inputs that do NOT satisfy the bug condition must be completely unaffected. This
includes:
- Advisories whose levels are fully `FL`-prefixed.
- `VA NOT IDENTIFIABLE`, `NO VA EXP`, missing, and non-string fields.
- The per-pair coordinate conversion path in `text_to_latlon()`.

**Note:** The expected correct behavior for bug-condition inputs is defined in the
Correctness Properties section (Property 1).

## Hypothesized Root Cause

Based on the bug description and the code, all three failures stem from the single
assumption that the `FL` prefix is always present on both bounds:

1. **Coordinate-parsing gate coupled to `FL`**: The entire coordinate-parsing block
   is nested inside `if "FL" in obs_text:`. Coordinate parsing has no logical
   dependence on the `FL` prefix; it was coupled only because the level extraction
   lived in the same block. When neither bound has `FL`, the substring is absent and
   parsing is skipped.

2. **Level-token regex requires `FL` after `/`**: `re.compile(r".*\S+/FL\S+")` only
   matches when the token following the `/` begins with `FL`. Bare or mixed bounds
   (`060/FL200`, `060/090`) do not match, so `time_and_level` is `""`, nothing is
   stripped, and the level token is consumed as a coordinate pair.

3. **Height mapping lacks a bare-number branch**: The loop handles `SFC` and `"FL"
   in fl`, but a bare `060` falls to `else: height = np.nan`. Because `np.nan in
   flight_levels` is then true, no `flight_level_txt` is produced. There is also a
   latent bug: `flight_levels` is only assigned inside `if time_and_level:`, so the
   later `if np.nan not in flight_levels:` would `NameError` if the token were empty;
   the current gate masks this, and the fix must keep `flight_levels` well-defined.

## Correctness Properties

Property 1: Bug Condition - Levels Without FL Prefix Parse Coordinates and Level Text

_For any_ input where the bug condition holds (isBugCondition returns true), the
fixed `process_polygons` SHALL return non-empty, equal-length `lons` and `lats`
lists equal to the coordinates parsed from the field (with the level token excluded,
never mis-parsed as a coordinate pair), and SHALL compute `flight_level_txt` by
mapping each bound via `SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` -> `xxx*100`.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - FL-Prefixed and Non-Coordinate Cases Unchanged

_For any_ input where the bug condition does NOT hold (isBugCondition returns false),
the fixed `process_polygons` SHALL produce the same result as the original function,
preserving the behavior for fully `FL`-prefixed levels, `VA NOT IDENTIFIABLE`, `NO
VA EXP`, missing/non-string fields, the `No polygons to plot` outcome, and per-pair
`text_to_latlon()` conversion.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming the root cause analysis is correct, the fix is confined to
`process_polygons()` in `src/volc_alarms/alarms/VAA/detection.py`. `text_to_latlon()`,
`get_extent()`, and `figure.py` are unchanged.

**File**: `src/volc_alarms/alarms/VAA/detection.py`

**Function**: `process_polygons(vaa, field)`

**Specific Changes**:

1. **Robust level-token regex**: Replace `re.compile(r".*\S+/FL\S+")` with a pattern
   that matches a `lower/upper` level where each bound is `FLxxx`, bare digits, or
   `SFC`, regardless of the `FL` prefix, e.g.:
   ```
   lvl_pattern = re.compile(r".*?(?:FL\d+|SFC|\d+)/(?:FL\d+|SFC|\d+)")
   ```
   This matches the leading time+level portion up through the second bound so it can
   be stripped, and matches `SFC/060`, `060/FL200`, `060/090`, and `SFC/FL060` alike.
   The token actually consumed by `text_to_latlon()` stripping must end at the level
   (before the first coordinate), matching the current behavior for `FL` cases.

2. **Decouple coordinate parsing from the `FL` gate**: Remove `if "FL" in obs_text:`
   as the guard around coordinate parsing. Always extract the level token, strip it
   from `obs_text`, split the remainder on `" - "`, and run `text_to_latlon()` per
   pair. The `VA NOT IDENTIFIABLE ` early-return and the non-string / missing-field
   early-returns stay in front of this block so those paths still yield empty lists.
   `NO VA EXP` forecast fields yield no coordinate pairs after stripping (no
   `Nxxxx Wxxxxx` tokens), preserving Req 3.4.

3. **Per-bound altitude helper**: Add a small helper (or inline branch) that maps a
   single bound string to an altitude:
   ```
   FUNCTION boundToAltitude(bound)
     IF bound == "SFC" THEN RETURN 0
     IF bound STARTS WITH "FL" THEN RETURN float(bound[2:]) * 100
     IF bound is all digits THEN RETURN float(bound) * 100
     RETURN np.nan   # genuinely unparseable -> suppress level text, as today
   END FUNCTION
   ```
   Apply it to both bounds obtained from `time_and_level.split(" ")[-1].split("/")`.

4. **Keep `flight_levels` well-defined**: Initialize `flight_levels = np.array([])`
   before the level loop and only build `flight_level_txt` when the token exists and
   both bounds resolve to non-NaN altitudes (`flight_levels.size == 2 and not
   np.isnan(flight_levels).any()`). This removes the latent `NameError` risk and
   preserves the "no level text when unparseable" behavior.

5. **Preserve level-text formatting**: Continue formatting as
   `f"{flight_levels[0]:,g} - {flight_levels[1]:,g} ft"` so `SFC/060` yields
   `0 - 6,000 ft` and existing `FL` cases render identically.

## Testing Strategy

### Validation Approach

Two phases: first surface counterexamples that demonstrate the bug on the UNFIXED
code, then verify the fix works for bug-condition inputs and preserves behavior for
everything else. The existing baseline harness
(`tests/alarms/test_regression.py`, `tests/alarms/scenarios.py`,
`tests/alarms/baselines/VAA_representative.json`) drives the alarm end-to-end; the
current `VAA_representative` scenario patches the download to `None` and exercises
the webpage-error path, so it does NOT cover polygon parsing. Bug-condition coverage
will be added with focused unit/property tests against `process_polygons()` directly
(no network, no matplotlib), plus an optional new scenario that feeds a crafted
advisory through `make_map()` to confirm a figure is generated.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the
fix, confirming the root-cause analysis. If a test unexpectedly passes on unfixed
code, re-hypothesize.

**Test Plan**: Call `process_polygons()` directly with crafted `vaa` dicts for each
bound-form combination and assert on the returned `(lons, lats, flight_level_txt)`.
Run on UNFIXED code first to observe the failures.

**Test Cases**:
1. **SFC/bare gate (MT KATMAI)**: `OBS VA CLD` =
   `SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR`
   -> expect 7 pairs and `0 - 6,000 ft` (will fail on unfixed code: empty lists).
2. **Mixed bound regex (`060/FL200`)**: a valid coordinate field with lower bound
   bare -> expect level token stripped and clean coordinates (will fail on unfixed
   code: token mis-parsed as first pair).
3. **Both bare (`060/090`)**: -> expect coordinates parsed and `6,000 - 9,000 ft`
   (will fail on unfixed code: gate skipped, empty lists).
4. **Out-of-form / edge**: a genuinely unparseable bound -> `flight_level_txt`
   remains `""` while coordinates still parse (documents the NaN-suppression edge).

**Expected Counterexamples**:
- `process_polygons()` returns empty `lons`/`lats` for `SFC/060` and `060/090`.
- The level token appears as a corrupted first coordinate for `060/FL200`.
- Possible causes: `FL` gate, `FL`-anchored regex, missing bare-number height branch.

### Fix Checking

**Goal**: Verify that for all bug-condition inputs, the fixed function produces the
expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  (lons, lats, level_txt) := process_polygons_fixed(input.vaa, input.field)
  ASSERT length(lons) > 0 AND length(lats) > 0
  ASSERT length(lons) == length(lats)
  ASSERT lons, lats EQUAL the coordinates parsed from input.field
         (level token NOT included as a coordinate pair)
  ASSERT level_txt computed via SFC -> 0, FLxxx -> xxx*100, bare xxx -> xxx*100
END FOR
```

### Preservation Checking

**Goal**: Verify that for all non-bug-condition inputs, the fixed function produces
the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT process_polygons_original(input.vaa, input.field)
       == process_polygons_fixed(input.vaa, input.field)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation because
it generates many inputs across the domain, catches edge cases manual tests miss,
and gives strong assurance that non-buggy behavior is unchanged.

**Test Plan**: Capture behavior on the UNFIXED code for `FL`-prefixed levels,
`VA NOT IDENTIFIABLE`, `NO VA EXP`, and missing/non-string fields, then write tests
(including property-based ones) asserting the fixed code matches.

**Test Cases**:
1. **FL-prefixed preservation**: `SFC/FL060` and `FL200/FL300` advisories parse to
   the same coordinates and level text after the fix as before.
2. **VA NOT IDENTIFIABLE preservation**: a field containing `VA NOT IDENTIFIABLE `
   still returns empty lists and empty level text.
3. **Missing / non-string field preservation**: absent field and non-string value
   still return `([], [], "")` without error.
4. **NO VA EXP preservation**: a forecast field with `NO VA EXP` yields no polygons.
5. **text_to_latlon preservation**: per-pair conversion for known tokens returns the
   same lat/lon values as before.

### Unit Tests

- `process_polygons()` for each bound-form combination: `SFC/060`, `060/FL200`,
  `060/090`, `SFC/FL060`, `FL200/FL300`.
- Level-text mapping: `SFC` -> 0, `FLxxx` -> `xxx*100`, bare `xxx` -> `xxx*100`, and
  the `0 - 6,000 ft` formatting for `SFC/060`.
- Non-coordinate cases: `VA NOT IDENTIFIABLE`, `NO VA EXP`, missing field, non-string
  field.
- The MT KATMAI counterexample asserting 7 coordinate pairs and `0 - 6,000 ft`.

### Property-Based Tests

- Generate levels as `lower/upper` where each bound is drawn from `{SFC, FLxxx,
  xxx}` with a randomly generated valid coordinate polygon; assert coordinates parse
  (count equals number of generated pairs) and level text matches the per-bound
  altitude mapping (Property 1).
- Generate the same over fully `FL`-prefixed and non-coordinate inputs and assert the
  fixed output equals the original output (Property 2).

### Integration Tests

- Extend the baseline harness with a crafted VAA advisory (e.g. an `SFC/060`
  observation) fed through `make_map()` and assert a figure is generated (not the
  `No polygons to plot` path), complementing the existing `VAA_representative`
  webpage-error scenario in `tests/alarms/scenarios.py`.
- Confirm the genuine no-coordinate advisory still logs `No polygons to plot. Not
  generating figure.` and skips figure generation (Req 3.5).
- Confirm the advisory title/level rendering in `figure.py` uses the new
  `flight_level_txt` (`0 - 6,000 ft`) unchanged in format.
