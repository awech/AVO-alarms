# Implementation Plan

## Overview

This plan fixes the FL-prefix assumption in `process_polygons()` (in `src/volc_alarms/alarms/VAA/detection.py`), which currently drops coordinates and mis-parses altitude bounds whenever a VAA level bound lacks an `FL` prefix (e.g. `SFC/060`, `060/FL200`, `060/090`). The fix replaces the FL-anchored level regex with a pattern that accepts `FLxxx`, `SFC`, or bare digits, decouples coordinate parsing from the `if "FL" in obs_text:` gate, and computes flight-level text from a per-bound altitude helper. Work follows the exploratory bugfix flow: write failing bug-condition tests and passing preservation tests before the fix, apply the fix, then re-run both to confirm the bug is resolved with no regressions.

## Tasks

- [x] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** - Levels Without FL Prefix Parse Coordinates and Level Text
  - **CRITICAL**: These tests MUST FAIL on the unfixed `process_polygons()` - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails at this step**
  - **NOTE**: These tests encode the expected behavior (Property 1 / Reqs 2.1-2.4); they will validate the fix once they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate the `FL`-prefix assumption is wrong
  - **Scoped PBT Approach**: This is a deterministic parsing bug, so scope the property to concrete bound-form combinations rather than fully random input
  - Add a test module (e.g. `tests/alarms/test_vaa_process_polygons.py`) that calls `process_polygons(vaa, field)` directly with crafted `vaa` dicts (no network, no matplotlib)
  - Encode the bug condition from the design: field present, is a string, not `VA NOT IDENTIFIABLE `, has valid coordinates, and at least one `/`-separated level bound lacks an `FL` prefix (`SFC` or bare digits)
  - Test case A - SFC/bare gate (MT KATMAI): `OBS VA CLD` = `SFC/060 N5825 W15450 - N5753 W15414 - N5741 W15329 - N5717 W15405 - N5741 W15459 - N5818 W15524 - N5825 W15450 STNR` -> assert 7 coordinate pairs (`len(lons) == len(lats) == 7`) and `flight_level_txt == "0 - 6,000 ft"`
  - Test case B - mixed bound regex (`060/FL200`): a valid coordinate field with a bare lower bound -> assert the level token is stripped and no coordinate pair is a corrupted `060/FL200 N...` value
  - Test case C - both bare (`060/090`): -> assert coordinates parse and `flight_level_txt == "6,000 - 9,000 ft"`
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (empty lists for A and C from the `FL` gate; corrupted first pair for B from the `FL`-anchored regex) - this is correct and proves the bug exists
  - Document the observed counterexamples (empty `lons`/`lats`, level token mis-parsed as a coordinate) to confirm the root cause
  - Mark this task complete when the tests are written, run, and their failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing the fix)
  - **Property 2: Preservation** - FL-Prefixed and Non-Coordinate Cases Unchanged
  - **IMPORTANT**: Follow the observation-first methodology - run the UNFIXED `process_polygons()`, record actual outputs, then assert those outputs
  - Observe and record baseline outputs on unfixed code for:
    - FL-prefixed levels: `SFC/FL060` and `FL200/FL300` advisories with valid coordinates (record parsed `lons`/`lats` and `flight_level_txt`)
    - `VA NOT IDENTIFIABLE ` field -> record `([], [], "")`
    - Missing field and non-string field value -> record `([], [], "")` returned without error
    - `NO VA EXP` forecast field -> record that no coordinate pairs are produced
    - `text_to_latlon()` per-pair conversion for known tokens (e.g. `N5825 W15450`) -> record returned lat/lon
  - Write property-based tests capturing the observed patterns (Property 2, Reqs 3.1-3.6):
    - Generate levels where BOTH bounds are `FLxxx` (fully FL-prefixed) with a random valid coordinate polygon; assert coordinate count equals the number of generated pairs and level text matches the FL altitude mapping
    - Generate the non-coordinate cases (`VA NOT IDENTIFIABLE`, `NO VA EXP`, missing/non-string field) and assert `([], [], "")`
    - Property-based generation gives stronger "for all non-buggy inputs" guarantees than fixed examples
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms the baseline behavior to preserve)
  - Mark this task complete when the tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix FL-prefix assumptions in `process_polygons()`

  - [x] 3.1 Implement the fix in `src/volc_alarms/alarms/VAA/detection.py`
    - Replace the FL-anchored regex `re.compile(r".*\S+/FL\S+")` with the robust pattern `re.compile(r".*?(?:FL\d+|SFC|\d+)/(?:FL\d+|SFC|\d+)")` so each bound matches `FLxxx`, `SFC`, or bare digits, and the token ends at the level (before the first coordinate)
    - Decouple coordinate parsing from the `if "FL" in obs_text:` gate: always extract/strip the level token, split the remainder on `" - "`, and run `text_to_latlon()` per pair; keep the `VA NOT IDENTIFIABLE `, missing-field, and non-string early-returns in front of this block
    - Add a per-bound altitude helper: `SFC` -> 0, `FLxxx` -> `float(xxx) * 100`, bare all-digits `xxx` -> `float(xxx) * 100`, otherwise `np.nan`; apply it to both bounds from `time_and_level.split(" ")[-1].split("/")`
    - Initialize `flight_levels = np.array([])` before the level loop (removes the latent `NameError`) and only build `flight_level_txt` when the token exists and both bounds resolve to non-NaN (`flight_levels.size == 2 and not np.isnan(flight_levels).any()`)
    - Preserve level-text formatting `f"{flight_levels[0]:,g} - {flight_levels[1]:,g} ft"` so `SFC/060` yields `0 - 6,000 ft`
    - _Bug_Condition: isBugCondition(vaa, field) - field present, string, not `VA NOT IDENTIFIABLE `, valid coordinates, and at least one `/`-separated bound lacks an `FL` prefix (from design)_
    - _Expected_Behavior: Property 1 - parse full coordinate set (level token excluded) and compute level text via SFC -> 0, FLxxx -> xxx*100, bare xxx -> xxx*100 (from design)_
    - _Preservation: Preservation Requirements - FL-prefixed levels, `VA NOT IDENTIFIABLE`, `NO VA EXP`, missing/non-string fields, and per-pair `text_to_latlon()` unchanged (from design)_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.2 Verify bug condition exploration tests now pass
    - **Property 1: Expected Behavior** - Levels Without FL Prefix Parse Coordinates and Level Text
    - **IMPORTANT**: Re-run the SAME tests from task 1 - do NOT write new tests
    - The tests from task 1 encode the expected behavior; when they pass they confirm it is satisfied
    - Run the bug condition exploration tests from task 1
    - **EXPECTED OUTCOME**: Tests PASS (MT KATMAI yields 7 pairs and `0 - 6,000 ft`; `060/FL200` strips the token; `060/090` yields `6,000 - 9,000 ft`) - confirms the bug is fixed
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - FL-Prefixed and Non-Coordinate Cases Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the preservation property tests from task 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions for FL-prefixed levels, `VA NOT IDENTIFIABLE`, `NO VA EXP`, missing/non-string fields, and per-pair conversion)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

- [x] 4. (Optional) Add a make_map integration scenario for a bug-condition advisory
  - Extend the baseline harness (`tests/alarms/scenarios.py`, `tests/alarms/test_regression.py`, `tests/alarms/baselines/VAA_representative.json`) with a crafted `SFC/060` VAA advisory fed through `make_map()`
  - Assert a figure IS generated (not the `No polygons to plot. Not generating figure.` path) for the bug-condition advisory
  - Assert a genuine no-coordinate advisory STILL logs `No polygons to plot. Not generating figure.` and skips figure generation
  - Confirm the title/level rendering uses the new `flight_level_txt` (`0 - 6,000 ft`) with unchanged format
  - _Requirements: 2.5, 3.5_

- [x] 5. Checkpoint - Ensure all tests pass
  - Run the full test suite (`process_polygons()` unit + property tests and the regression harness) with a single-run flag (no watch mode)
  - Confirm exploration tests (task 1) now pass, preservation tests (task 2) still pass, and no other regressions were introduced
  - Ensure all tests pass; ask the user if questions arise

## Task Dependency Graph

```
Task 1 (Bug condition exploration tests) ─┐
                                          ├─► Task 3.1 (Implement the fix)
Task 2 (Preservation property tests) ─────┘        │
                                                   ├─► Task 3.2 (Verify exploration tests pass)
                                                   └─► Task 3.3 (Verify preservation tests pass)
                                                            │
                                          Task 4 (Optional make_map scenario, after Task 3)
                                                            │
                                                            ▼
                                          Task 5 (Checkpoint - all tests pass) ── last
```

```json
{
  "waves": [
    { "id": 1, "tasks": ["1", "2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3"] },
    { "id": 4, "tasks": ["4"] },
    { "id": 5, "tasks": ["5"] }
  ]
}
```

Ordering rules:
- Tasks 1 and 2 MUST be completed before Task 3 (tests are written and run against the unfixed code first).
- Task 3.1 MUST precede 3.2 and 3.3 (the fix is applied before re-running the tests).
- Task 4 is optional and runs after Task 3 (integration coverage on the fixed code).
- Task 5 is the final checkpoint and runs last, after all other tasks.

## Notes

- All `process_polygons()` tests call the function directly with crafted `vaa` dicts - no network access and no matplotlib rendering are required for the unit/property tests.
- Tasks 1 and 2 are intentionally run against the UNFIXED code: task 1 tests MUST fail (proving the bug) and task 2 tests MUST pass (capturing baseline behavior to preserve).
- The bug is deterministic parsing, so bug-condition properties are scoped to concrete bound-form combinations (`SFC/060`, `060/FL200`, `060/090`) rather than fully random input.
- Preservation tests use the observation-first methodology: record actual outputs from the unfixed code before asserting them.
- Run the suite with a single-run flag (no watch mode) so the checkpoint terminates cleanly.
- The fix also initializes `flight_levels = np.array([])` before the level loop to remove a latent `NameError`; keep the existing `VA NOT IDENTIFIABLE `, missing-field, and non-string early-returns ahead of the coordinate-parsing block.
