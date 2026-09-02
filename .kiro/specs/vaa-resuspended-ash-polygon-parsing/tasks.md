# Implementation Plan

## Overview

This plan expands the VAA polygon-parsing fix to cover the real-world forecast /
multi-ring format that crashed production (`run-alarm --test -t 202609010000 VAA` ->
`ValueError: could not convert string to float: '-FC/060'`). The fix (a) changes the
`process_polygons()` return contract from a single `(lons, lats, flight_level_txt)`
tuple to a LIST of per-sub-polygon groups `[(lons, lats, level_txt), ...]`, (b) adds
context-guarded level detection that skips the leading `DD/HHMM` time token, (c)
splits a field into sub-polygon segments and strips trailing `MOV ... KT` motion
tokens, (d) handles per-sub-polygon `NO VA EXP`, and (e) updates `make_map()` to plot
each ring separately (one legend entry per field) with a comma-separated multi-level
title. `text_to_latlon()` and `get_extent()` are unchanged.

Because the return contract changes to a list, the tests written for the original
single-tuple scope MUST be revised: `tests/alarms/test_vaa_process_polygons.py`,
`tests/alarms/test_vaa_process_polygons_preservation.py`, and
`tests/alarms/test_vaa_make_map.py`. Work follows the exploratory bugfix flow: write /
adjust failing bug-condition tests for the NEW real-format cases first, revise the
preservation tests to the new contract, apply the fix in `detection.py` and
`figure.py`, then re-run both.

## Tasks

- [x] 1. Write / adjust bug-condition exploration tests for the new real-format cases
  - **Property 1: Bug Condition** - Real-Format Cloud Fields Parse Every Ring
  - **CRITICAL**: These tests MUST FAIL on the unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails at this step**
  - **NOTE**: These tests encode the expected behavior (Property 1 / Reqs 2.1-2.9); they will validate the fix once they pass
  - **GOAL**: Surface counterexamples for the forecast time token, multiple sub-polygons, MOV tokens, and per-sub-polygon `NO VA EXP`
  - Revise `tests/alarms/test_vaa_process_polygons.py` to the NEW list contract: `process_polygons(vaa, field)` now returns a LIST of `(lons, lats, level_txt)` groups. Update the existing MT KATMAI / `060/FL200` / `060/090` cases to assert `groups == [ (lons, lats, level_txt) ]` (single-element list, one ring)
  - Add NEW bug-condition cases:
    - Forecast time-token crash: `FCST VA CLD +6HR` = `01/0858Z FL100/FL340 N4941 W16417 - ... - N4941 W16417 MOV ESE 70KT` then newline `FL100/FL280 NO VA EXP` -> assert (post-fix) one ring for `FL100/FL340` with `level_txt == "10,000 - 34,000 ft"`, the `NO VA EXP` sub-polygon skipped, and NO `ValueError` raised. On UNFIXED code this raises `ValueError: could not convert string to float: '-FC/060'`
    - Two-ring OBS field: `FL100/FL340 ... MOV ESE 70KT` / `FL100/FL280 ... MOV SE 50KT` -> assert `len(groups) == 2` with `level_txt` `"10,000 - 34,000 ft"` and `"10,000 - 28,000 ft"`
    - MOV motion token: assert no parsed coordinate derives from `MOV ESE 70KT` / `MOV SE 50KT`
    - Per-sub-polygon `NO VA EXP`: a `FL100/FL280 NO VA EXP` segment beside a real ring -> only the real ring returned, no crash
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (ValueError on the forecast field; dropped/merged second ring; MOV mis-parsed) - this is correct and proves the bug exists
  - Document the observed counterexamples to confirm the root cause (single-polygon model, time-token regex match, no MOV / per-sub `NO VA EXP` handling)
  - Mark complete when the tests are written, run, and their failure is documented
  - _Requirements: 1.4, 1.5, 1.6, 1.7, 2.5, 2.6, 2.7, 2.8, 2.9_

- [x] 2. Revise preservation tests to the new list contract (BEFORE implementing the fix)
  - **Property 2: Preservation** - Single-Ring FL and Non-Coordinate Cases Unchanged
  - **IMPORTANT**: Follow the observation-first methodology - record actual outputs, then assert them under the new contract
  - Revise `tests/alarms/test_vaa_process_polygons_preservation.py` to the NEW list contract:
    - Single-ring FL-prefixed levels (`SFC/FL060`, `FL200/FL300`): assert `groups == [ (lons, lats, level_txt) ]` - a single-element list whose one group equals the recorded coordinates and level text (previously asserted as a bare tuple)
    - `VA NOT IDENTIFIABLE ` field -> assert `groups == []`
    - Missing field and non-string field value -> assert `groups == []` without error
    - Whole-field `NO VA EXP` forecast field -> assert `groups == []`
    - Newline-wrapped coordinates within a ring -> assert they still join correctly (Req 3.7)
    - `text_to_latlon()` per-pair conversion for known tokens -> assert the recorded lat/lon (unchanged; Req 3.6)
  - Run the revised preservation tests on UNFIXED code where the case is still expressible; for the single-ring FL cases note that the OLD code returns a bare tuple, so these specific assertions will only pass after the fix wraps them in a list - keep them but mark them as encoding the post-fix contract, while the non-coordinate cases (`[]`) can be validated by observation of the old empty-tuple result mapped to `[]`
  - **EXPECTED OUTCOME**: Non-coordinate baseline behavior is captured; single-ring FL wrapping is asserted for post-fix verification
  - Mark complete when the preservation tests are revised and their baseline behavior is recorded
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7_

- [x] 3. Fix the real-format parsing and rendering

  - [x] 3.1 Implement the new list contract and segment parsing in `src/volc_alarms/alarms/VAA/detection.py`
    - Change `process_polygons(vaa, field)` to return a LIST of `(lons, lats, level_txt)` groups (one per parsed ring); keep the missing-field, non-string, `VA NOT IDENTIFIABLE `, and whole-field `NO VA EXP` early-returns but have them `return []`
    - Preserve the newline-to-space normalization first (handles wrapped coordinates)
    - Add context-guarded level detection: recognize a level ONLY where a `(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)` bound-pair is immediately followed by whitespace and a coordinate token (`[NS]\d`), e.g. `re.compile(r"(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)(?=\s+[NS]\d)")`; this skips the leading `DD/HHMM` time token (which is followed by the level, not a coordinate; the trailing `Z` may be absent so it is NOT relied on) and digit runs inside coordinates
    - Split the field into sub-polygon segments at each level-token boundary (one segment per level match, spanning to the next level token / end of field); capture the two bounds and the coordinate run per segment
    - Strip the leading time token(s) and trailing `MOV ... KT` motion tokens from each segment's coordinate run before per-pair `text_to_latlon()` (e.g. `re.sub(r"\s*MOV\s+\S+\s+\d+KT.*$", "", coords)`)
    - Per-sub-polygon `NO VA EXP`: if a segment has no coordinate token, yield no group and continue to the next sibling without error
    - Per-bound altitude mapping unchanged: `SFC` -> 0, `FLxxx` -> `float(xxx)*100`, bare all-digit `xxx` -> `float(xxx)*100`, else `np.nan`; emit `level_txt` only when both bounds resolve to non-NaN, formatting `f"{lo:,g} - {hi:,g} ft"`; a ring with an unparseable bound still returns its coordinates with `level_txt == ""`
    - _Bug_Condition: isBugCondition(vaa, field) - field present, string, not `VA NOT IDENTIFIABLE ` / whole-field `NO VA EXP`, has a valid ring, and exhibits a real-format feature (no-FL bound, leading time token, multiple sub-polygons, MOV token, or per-sub `NO VA EXP`) (from design)_
    - _Expected_Behavior: Property 1 - one group per ring, level / time / MOV tokens excluded from coordinates, per-bound altitude mapping (from design)_
    - _Preservation: Property 2 - single-ring FL fields wrap to a one-element list; non-coordinate cases return `[]`; `text_to_latlon()` unchanged (from design)_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 3.2 Update `make_map()` in `src/volc_alarms/alarms/VAA/figure.py` to consume the list and plot each ring
    - For each field call `groups = process_polygons(vaa, field)` and gather all rings' coordinates for the `LONS`/`LATS` union and `get_extent()` (extent logic unchanged)
    - Plot EACH ring of a field as its own `ax.plot(...)` line (no spurious connecting segment between distinct rings), applying that field's existing style to each ring: OBS firebrick solid lw 1.5 zorder 100, +6H orangered dashed lw 1.25 zorder 99, +12H orange dashed lw 1 zorder 98, +18H goldenrod dash-dot lw 0.75 zorder 97
    - Keep a single legend entry per field: label only the FIRST ring of each field; subsequent rings use `label='_nolegend_'`
    - Build the title from ALL DISTINCT OBS `level_txt` values, comma-separated (e.g. `10,000 - 34,000 ft, 10,000 - 28,000 ft`), preserving the format `f"{volcano_name} VAA\n{levels}\n{vaa_time}"`
    - Keep the no-polygons path: when NO rings exist across every field, still log `No polygons to plot. Not generating figure.` and return `[]`
    - _Bug_Condition: multi-ring / multi-level fields (from design)_
    - _Expected_Behavior: Req 2.10 (per-ring plotting, single legend per field) and Req 2.11 (multi-level title) (from design)_
    - _Preservation: Req 3.5 - the global no-polygons path is unchanged (from design)_
    - _Requirements: 2.10, 2.11, 3.5_

  - [x] 3.3 Revise `tests/alarms/test_vaa_make_map.py` to the new list contract
    - Update the make_map integration tests to the list contract: use the user's real two-ring OBS field plus the `01/0858Z` forecast field (mock `figure.plotting.save_file`)
    - Assert a figure IS generated for the bug-condition advisory (not the `No polygons to plot` path)
    - Assert each ring is plotted as a separate line and the legend has one entry per field
    - Assert the title lists all distinct OBS levels comma-separated (`10,000 - 34,000 ft, 10,000 - 28,000 ft`)
    - Keep a genuine no-coordinate advisory asserting the `No polygons to plot. Not generating figure.` skip path
    - _Requirements: 2.10, 2.11, 3.5_

  - [x] 3.4 Verify bug-condition exploration tests now pass
    - **Property 1: Expected Behavior** - Real-Format Cloud Fields Parse Every Ring
    - **IMPORTANT**: Re-run the SAME tests from task 1 - do NOT write new tests
    - Run the bug-condition exploration tests from task 1
    - **EXPECTED OUTCOME**: Tests PASS (forecast field yields one `FL100/FL340` ring with no crash; two-ring OBS field yields two rings; MOV tokens excluded; per-sub `NO VA EXP` skipped) - confirms the bug is fixed
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Single-Ring FL and Non-Coordinate Cases Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the revised preservation tests from task 2
    - **EXPECTED OUTCOME**: Tests PASS (single-ring FL fields wrap to a one-element list matching the baseline; `VA NOT IDENTIFIABLE`, whole-field `NO VA EXP`, missing/non-string fields return `[]`; `text_to_latlon()` unchanged) - confirms no regressions
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7_

- [x] 4. (Optional) Integration scenario using the user's real multi-ring example
  - Add an integration test / scenario that feeds the real two-ring OBS field and the `01/0858Z` forecast field through `make_map()` end-to-end (mock `save_file`)
  - Assert the figure is generated with each ring as a separate line, one legend entry per field, and the multi-level title
  - Confirm a genuine no-coordinate advisory still logs `No polygons to plot. Not generating figure.` and skips the figure
  - _Requirements: 2.10, 2.11, 3.5_

- [x] 5. Checkpoint - Ensure all tests pass
  - Run the full test suite (`process_polygons()` unit + property tests, `make_map()` integration tests, and the regression harness) with a single-run flag (no watch mode)
  - Confirm exploration tests (task 1) now pass, preservation tests (task 2) still pass, and no other regressions were introduced
  - Ensure all tests pass; ask the user if questions arise

## Task Dependency Graph

```
Task 1 (Bug-condition exploration tests, new real-format cases) ─┐
                                                                 ├─► Task 3.1 (list contract + segment parsing in detection.py)
Task 2 (Revise preservation tests to list contract) ────────────┘        │
                                                                          ├─► Task 3.2 (make_map: per-ring plot + multi-level title)
                                                                          │        │
                                                                          │        └─► Task 3.3 (revise test_vaa_make_map.py)
                                                                          │
                                                                          ├─► Task 3.4 (verify exploration tests pass)
                                                                          └─► Task 3.5 (verify preservation tests pass)
                                                                                   │
                                                              Task 4 (Optional real multi-ring integration scenario, after Task 3)
                                                                                   │
                                                                                   ▼
                                                              Task 5 (Checkpoint - all tests pass) ── last
```

```json
{
  "waves": [
    { "id": 1, "tasks": ["1", "2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2"] },
    { "id": 4, "tasks": ["3.3", "3.4", "3.5"] },
    { "id": 5, "tasks": ["4"] },
    { "id": 6, "tasks": ["5"] }
  ]
}
```

Ordering rules:
- Tasks 1 and 2 MUST be completed before Task 3 (tests are written / revised and run against the unfixed code first; task 1 tests MUST fail, capturing the bug).
- Task 3.1 (detection.py list contract) MUST precede 3.2 (make_map consumes the list) and the verification sub-tasks.
- Task 3.2 MUST precede 3.3 (the make_map test revision asserts the new per-ring / multi-level rendering).
- Tasks 3.4 and 3.5 re-run the SAME tests from tasks 1 and 2 after the fix.
- Task 4 is optional and runs after Task 3 (end-to-end coverage on the fixed code).
- Task 5 is the final checkpoint and runs last.

## Notes

- **Contract change**: `process_polygons()` now returns a LIST of `(lons, lats, level_txt)` groups. Every test and `make_map()` caller must be updated; the three existing test files were written for the old single-tuple contract and are explicitly revised in tasks 1, 2, and 3.3.
- All `process_polygons()` tests call the function directly with crafted `vaa` dicts - no network access is required. `make_map()` tests mock `figure.plotting.save_file` to avoid disk writes.
- Tasks 1 and 2 run against the UNFIXED code: task 1 tests MUST fail (the forecast field raises `ValueError: could not convert string to float: '-FC/060'`, the second ring is dropped, MOV tokens are mis-parsed), proving the bug.
- Level detection is context-guarded (`(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)(?=\s+[NS]\d)`) to skip the leading `DD/HHMM` time token; trailing `MOV ... KT` tokens are stripped before coordinate conversion.
- `text_to_latlon()` and `get_extent()` are NOT modified by this fix.
- Run the suite with a single-run flag (no watch mode) so the checkpoint terminates cleanly.
