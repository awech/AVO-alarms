# Implementation Plan: alarm-modules-restructure

## Overview

This plan restructures the `avo_alarms` package while preserving exact runtime
behavior of the live alerting pipelines. Behavior preservation is the gating
constraint, so the plan **captures frozen behavior baselines and a test harness
before any code is relocated or refactored**. Only after the safety net exists
do we build the shared flow templates, relocate the shared spectrogram figure
builder, convert each alarm into a package (moving single-consumer functions
into their owning package), and finally remove the now-orphaned definitions from
`utils/` and verify import/contract integrity.

Implementation language: **Python** (matches the existing codebase and the
design document). Tests use `pytest`; the single correctness property uses
**Hypothesis**.

## Tasks

- [ ] 1. Establish behavior-preservation harness and baselines (gating — before any refactor)
  - [ ] 1.1 Create test package structure and shared test doubles
    - Add a `tests/alarms/` package (with `conftest.py`) for alarm-level tests
    - Point `CONFIGS_DIR` at the in-repo `config/` directory (the `.py` config
      modules now checked into the repo) and load configs via
      `setup_utils.load_config`, so `run_alarm` is driven with real config
      objects rather than mocked stand-ins (the `config/*.yml` files in that
      directory are not consumed)
    - Implement reusable test doubles that replace all external side effects:
      `downloading.download_waveforms`, `download_hypocenters_csv`,
      `download_hypocenter_xml`, and the relocated `download_*` functions
      (return canned fixtures); `messaging.post_mattermost`, `send_alert`,
      `icinga` (record call args/order, no I/O); `alarming.can_send`,
      `record_send`, `filter_dataframe`/DB access (in-memory/mocked);
      figure builders / `plotting.save_file` (return a sentinel path);
      `os.remove` (record the call); and a helper to set `FROMCRON` per test
    - _Requirements: 10.1, 12.1_
  - [ ] 1.2 Capture and freeze golden behavior baselines from the current (pre-restructure) code
    - Drive each alarm's `run_alarm` with recorded input fixtures using the
      doubles from 1.1 and snapshot the Behavior_Baseline: detection `state`,
      Icinga state + state message, `CRITICAL` message subject/body,
      `record_send` fields (`alarm_id`, `volcano`, `event_id`, processed time),
      and the `os.remove` cleanup call
    - Persist these snapshots as frozen fixtures so later golden tests assert
      restructured output equals them
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_

- [ ] 2. Create shared flow templates in `utils/alarm_flow.py`
  - [ ] 2.1 Implement `apply_cron_latency_backup(config, T0, extra_sleep=0.0)`
    - New module `utils/alarm_flow.py`; import only `messaging`, `alarming`,
      `setup_utils` to preserve the layered, acyclic dependency direction
    - Reproduce the Cron_Latency_Backup math: `FROMCRON == "yep"` and
      `latency < 30` → sleep `latency + extra_sleep`, return `T0`;
      `FROMCRON == "yep"` and `latency >= 30` → return
      `T0 - ceil(latency / 60) * 60`, no sleep; otherwise return `T0`, no sleep
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [ ]* 2.2 Write Hypothesis property test for the cron-latency time math
    - **Property 1: Cron latency backup time math**
    - **Validates: Requirements 7.3, 7.4, 7.5**
    - Tag the test: `Feature: alarm-modules-restructure, Property 1`; run 100+
      iterations over the latency domain and both `FROMCRON` states; assert the
      returned `T0` and sleep behavior for all three branches
  - [ ] 2.3 Implement `run_send_sequence(...)` template
    - In `utils/alarm_flow.py`, implement the single Send_Sequence: `can_send`
      rate-limit check → `figure_factory()` guarded by try/except →
      `message_factory()` → `post_mattermost` guarded by try/except →
      `send_alert` → `record_send` → `os.remove(filename)` if produced →
      `icinga` heartbeat; accept and forward `can_send_kwargs`/`record_kwargs`,
      and the `mm_flag`/`icinga_flag`/`test_flag` flags
    - On `can_send` False: append rate-limit note, send Icinga heartbeat, return
      without `send_alert`/`record_send`. On figure failure: log and continue
      with `filename = None`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [ ]* 2.4 Write send-sequence ordering/branch unit tests
    - Assert call order `can_send → figure_factory → message_factory →
      post_mattermost → send_alert → record_send → os.remove → icinga` (8.3)
    - Assert `can_send` False skips `send_alert`/`record_send`, appends the
      rate-limit note, still calls `icinga` (8.4); figure failure yields
      `filename is None` and `post_mattermost`/`send_alert` get `attachment=None`
      (8.5); `can_send_kwargs`/`record_kwargs` forwarding reaches both callees (8.6)
    - _Requirements: 8.3, 8.4, 8.5, 8.6, 12.4_

- [ ] 3. Relocate the shared spectrogram figure builder
  - [ ] 3.1 Add `plot_spectrogram_figure(nslc, T0, config, test=False)` to `utils/plotting.py`
    - Move the body of the current `RSAM.make_figure` (generic spectrogram
      mosaic over a list of NSLC) into `utils/plotting.py` as a shared builder
      consumed by RSAM and Tremor; do not delete `RSAM.make_figure` yet (the
      RSAM file is replaced in task 5.3)
    - _Requirements: 5.1, 5.2, 11.4_
  - [ ]* 3.2 Write unit test for `plot_spectrogram_figure`
    - With waveform/`save_file` doubles, assert it returns the sentinel path and
      builds one mosaic row per trace
    - _Requirements: 5.2_

- [ ] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Restructure the three consolidated alarms (Infrasound, RSAM, Tremor)
  - [ ] 5.1 Convert Infrasound into an Alarm_Package wired to the shared templates
    - Create `alarm_codes/Infrasound/` with `__init__.py` (the `run_alarm`
      skeleton, signature unchanged), `detection.py`
      (`setup_coordinate_system`, `calc_triggers`, `associator`, `inversion`,
      `xcorr_align_stream`, `get_target_backazimuth`), `figure.py`
      (`make_figure` — the Infrasound stack/seismic figure), and `message.py`
      (`create_message`)
    - Replace the inline cron block with
      `T0 = apply_cron_latency_backup(config, T0)` and the inline CRITICAL block
      with `run_send_sequence(...)`, passing
      `can_send_kwargs={"volcano": target["name"]}` and
      `record_kwargs={"volcano": target["name"]}` plus figure/message factories
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 6.1, 6.2, 6.3, 7.2, 8.2, 11.1, 11.2, 11.3_
  - [ ]* 5.2 Write golden behavior-preservation test for Infrasound
    - Drive `Infrasound.run_alarm` with recorded fixtures; assert state,
      Icinga state/message, CRITICAL subject/body, `record_send` fields, and
      `os.remove` match the frozen baseline from 1.2
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 5.3 Convert RSAM into an Alarm_Package (relocate `RSAM_to_DR`, thin figure wrapper)
    - Create `alarm_codes/RSAM/` with `__init__.py` (`run_alarm` skeleton),
      `detection.py` (relocated `RSAM_to_DR`), `figure.py` (thin `make_figure`
      delegating to `plotting.plot_spectrogram_figure`), and `message.py`
      (`create_message`); remove the old `alarm_codes/RSAM.py`
    - Replace inline cron block with `apply_cron_latency_backup(config, T0)` and
      inline CRITICAL block with `run_send_sequence(...)` (empty
      `can_send_kwargs`/`record_kwargs`); import `RSAM_to_DR` from `.detection`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.5, 7.2, 8.2, 11.1, 11.3_
  - [ ]* 5.4 Write golden behavior-preservation test for RSAM
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 5.5 Convert Tremor into an Alarm_Package and remove the Tremor→RSAM import
    - Create `alarm_codes/Tremor/` with `__init__.py` (`run_alarm` skeleton),
      `detection.py` (`test_traveltime`, `run_enveloc`, `remove_hp_detects`,
      `preprocess`, `qc_checks`, `make_env`, `create_icinga_test`), `figure.py`
      (thin `make_figure` → `plotting.plot_spectrogram_figure`), and
      `message.py` (`create_message`); remove the old `alarm_codes/Tremor.py`
    - Drop `from avo_alarms.alarm_codes import RSAM`; call local
      `figure.make_figure`; replace cron block with
      `apply_cron_latency_backup(config, T0, extra_sleep=config.taper)` and the
      CRITICAL block with `run_send_sequence(...)` using
      `record_kwargs={"volcano": config.volcano}`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 7.2, 8.2, 11.1, 11.2, 11.3, 11.4_
  - [ ]* 5.6 Write golden behavior-preservation test for Tremor
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline (including the `latency + taper` sleep)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_

- [ ] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Restructure the event-id de-dup alarms (Lightning, NOAA_CIMSS, Pilot_Report, SO2, VAA)
  - [ ] 7.1 Convert Lightning into an Alarm_Package (relocate `download_lightning`)
    - Create `alarm_codes/Lightning/` with `__init__.py`, `detection.py`
      (relocated `download_lightning` plus `inner_outer`, `get_state_message`,
      `get_direction`), `figure.py` (`plot_fig`), `message.py`; import
      `download_lightning` from `.detection`; keep shared
      `find_nearest_volcano`/`filter_dataframe` imports from `utils`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.2, 4.3, 4.5, 11.1, 11.3_
  - [ ]* 7.2 Write golden behavior-preservation test for Lightning
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 7.3 Convert NOAA_CIMSS into an Alarm_Package (relocate CIMSS-only functions)
    - Create `alarm_codes/NOAA_CIMSS/` with `__init__.py`, `detection.py`
      (relocated `download_cimss_vv_api`, `scrape_cimss_alert`,
      `get_cimss_image`, `format_cimss_dataframe`, `check_ignore_volcano`, plus
      its soup parsers), `figure.py` (`plot_fig`), and `message.py`
      (`create_message` plus relocated `cimss_mm_channels`); import relocated
      functions from local submodules
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.5, 4.1, 4.2, 4.3, 4.5, 11.1, 11.3_
  - [ ]* 7.4 Write golden behavior-preservation test for NOAA_CIMSS
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 7.5 Convert Pilot_Report into an Alarm_Package (relocate PIREP-only functions)
    - Create `alarm_codes/Pilot_Report/` with `__init__.py`, `detection.py`
      (relocated `download_pilot_reports`, `pirep_archive_to_dataframe`,
      `check_volcano_mention`, plus `get_height_text`, `get_pilot_remark`),
      `figure.py` (`plot_fig`), `message.py`; import relocated functions locally
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.2, 4.3, 4.5, 11.1, 11.3_
  - [ ]* 7.6 Write golden behavior-preservation test for Pilot_Report
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 7.7 Convert SO2 into an Alarm_Package (relocate `download_SO2`)
    - Create `alarm_codes/SO2/` with `__init__.py`, `detection.py` (relocated
      `download_SO2` plus `get_so2_images`), `figure.py` (`plot_fig`),
      `message.py`; import `download_SO2` from `.detection`; keep shared
      `volcano_distance`/`format_timestring` imports from `utils`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.2, 4.3, 4.5, 11.1, 11.3_
  - [ ]* 7.8 Write golden behavior-preservation test for SO2
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 7.9 Convert VAA into an Alarm_Package (relocate `download_mesonet_vaa_list`)
    - Create `alarm_codes/VAA/` with `__init__.py`, `detection.py` (relocated
      `download_mesonet_vaa_list` plus `process_vaa_id`, `process_polygons`,
      `text_to_latlon`, `get_extent`), `figure.py` (VAA `make_map`),
      `message.py`; import `download_mesonet_vaa_list` from `.detection`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.2, 4.3, 4.5, 11.1, 11.3_
  - [ ]* 7.10 Write golden behavior-preservation test for VAA
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_

- [ ] 8. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Restructure the remaining alarms (Magnitude, Swarm)
  - [ ] 9.1 Convert Magnitude into an Alarm_Package
    - Create `alarm_codes/Magnitude/` with `__init__.py`, `detection.py`
      (`process_event`), `figure.py` (`plot_event`), `message.py`; import
      shared `addPhaseHint`, `eq_picks_to_dataframe`, `find_nearest_volcano`,
      `volcano_distance`, `download_hypocenters_csv`/`_xml` from `utils`
      (these stay shared per the litmus test)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.5, 5.1, 5.4, 11.1, 11.3_
  - [ ]* 9.2 Write golden behavior-preservation test for Magnitude
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_
  - [ ] 9.3 Convert Swarm into an Alarm_Package
    - Create `alarm_codes/Swarm/` with `__init__.py`, `detection.py`
      (`get_swarms`, `check_swarm_continue`, `compare_swarms`,
      `build_download_url`), `figure.py` (Swarm `make_figure`), `message.py`;
      import shared `addPhaseHint`, `eq_picks_to_dataframe`,
      `download_hypocenters_csv`/`_xml`, `find_nearest_volcano` from `utils`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 3.5, 5.1, 5.4, 11.1, 11.3_
  - [ ]* 9.4 Write golden behavior-preservation test for Swarm
    - Assert state, Icinga, CRITICAL subject/body, `record_send`, and
      `os.remove` match the frozen baseline
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 12.2, 12.3_

- [ ] 10. Remove orphaned definitions from Shared_Utils and verify integrity
  - [ ] 10.1 Delete relocated single-consumer functions from `utils/`
    - Remove from `processing.py`: `RSAM_to_DR`, `check_ignore_volcano`,
      `format_cimss_dataframe`, `pirep_archive_to_dataframe`,
      `check_volcano_mention`; from `downloading.py`: `download_lightning`,
      `download_cimss_vv_api`, `scrape_cimss_alert`, `get_cimss_image`,
      `download_pilot_reports`, `download_mesonet_vaa_list`, `download_SO2`;
      from `messaging.py`: `cimss_mm_channels`
    - Keep `download_station_xml` (script consumer) and the shared functions
      (`addPhaseHint`, `eq_picks_to_dataframe`, `find_nearest_volcano`,
      `volcano_distance`, etc.) in place; leave config files untouched
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.4, 5.1, 5.2, 5.3, 5.4, 11.3_
  - [ ]* 10.2 Write import / contract smoke tests
    - For every `alarm_type`, assert
      `import_module(f"avo_alarms.alarm_codes.{alarm_type}")` succeeds and
      exposes a callable `run_alarm` whose `inspect.signature` equals
      `(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False)`
    - Assert each relocated function imports from its new owner and is **no
      longer** importable from the old `utils` module; assert no `utils/*`
      module imports `avo_alarms.alarm_codes` and no alarm package imports
      another alarm package
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.4, 11.1, 11.2, 11.3, 11.4_

- [ ] 11. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a
  faster path, but the golden behavior-preservation tests are the safety net for
  this refactor and are strongly recommended.
- Tasks 1.1 and 1.2 are intentionally **not** optional and run **first**: the
  behavior baselines must be captured against the pre-restructure code so any
  regression introduced by relocation/refactoring is caught.
- Each alarm-package conversion relocates only that alarm's single-consumer
  functions; the actual deletion from `utils/` is deferred to task 10.1 so the
  shared utility files are edited in exactly one task (avoids parallel conflicts).
- Property test validates the one universal correctness property (cron-latency
  time math). All other criteria are covered by golden, ordering/branch, and
  import/contract example tests.
- The runtime `.py` config modules (loaded from `CONFIGS_DIR` via
  `setup_utils.load_config`) and `utils/setup_utils.py` signatures are unchanged
  throughout (Req 10).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "7.1", "7.3", "7.5", "7.7", "7.9", "9.1", "9.3"] },
    { "id": 3, "tasks": ["2.4", "5.1", "5.3", "5.5"] },
    { "id": 4, "tasks": ["5.2", "5.4", "5.6", "7.2", "7.4", "7.6", "7.8", "7.10", "9.2", "9.4"] },
    { "id": 5, "tasks": ["10.1"] },
    { "id": 6, "tasks": ["10.2"] }
  ]
}
```
