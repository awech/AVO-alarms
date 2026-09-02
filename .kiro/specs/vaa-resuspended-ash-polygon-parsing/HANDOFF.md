# Handoff: vaa-resuspended-ash-polygon-parsing

## Context
Bugfix spec for VAA resuspended-ash polygon parsing. Work was started in a
production checkout (`/alarms/volc-alarms`, on `main`) and moved into this
dev workspace to continue testing safely off the production branch.

## The bug (root cause)
`process_polygons()` in `src/volc_alarms/alarms/VAA/detection.py` assumes every
`/`-separated flight-level bound carries an `FL` prefix:
- An `if "FL" in obs_text:` gate skips coordinate parsing entirely when neither
  bound has `FL` (e.g. `SFC/060`, `060/090`) -> empty `lons`/`lats`.
- An `FL`-anchored regex (`.*\S+/FL\S+`) fails to strip a bare lower bound when
  only the upper bound has `FL` (e.g. `060/FL200`), so the level token is
  mis-parsed as the first coordinate pair.

## Progress so far
- **Task 1 (bug condition exploration tests):** test file written at
  `tests/alarms/test_vaa_process_polygons.py` with three cases:
  - A - `SFC/060` (MT KATMAI): expects 7 coord pairs, `flight_level_txt == "0 - 6,000 ft"`
  - B - `060/FL200`: level token must be stripped, not mis-parsed as a coordinate
  - C - `060/090`: expects 7 coord pairs, `flight_level_txt == "6,000 - 9,000 ft"`
- No `src/` production code has been modified yet.
- Task 1 was left `in_progress` in the tracker (an execution run was aborted
  before formal completion).

## Next steps
1. Run the exploration tests on the UNFIXED code:
   `pytest tests/alarms/test_vaa_process_polygons.py -v`
2. Confirm they FAIL as expected. That failure is the SUCCESS signal - it
   confirms the bug exists. Expected counterexamples:
   - A and C: empty `lons`/`lats` (skipped by the `FL` gate)
   - B: corrupted first pair from the level token `060/FL200` not being stripped
3. Document the counterexamples and mark Task 1 complete.
4. Proceed to the fix tasks in `tasks.md`.

## Notes
- This is a bugfix workflow: Task 1 tests are meant to fail on unfixed code.
- Start a fresh Kiro chat in this workspace and point it at this spec folder to
  resume; the spec files plus this note contain the full context.
