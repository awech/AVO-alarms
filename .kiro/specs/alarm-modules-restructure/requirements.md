# Requirements Document

## Introduction

The `avo_alarms` package runs a set of live volcano-monitoring alarms (Infrasound, RSAM, Tremor, Lightning, NOAA_CIMSS, Pilot_Report, SO2, Swarm, Magnitude, VAA). Each alarm currently lives in a single module under `alarm_codes/` and shares three generic utility modules (`utils/processing.py`, `utils/plotting.py`, `utils/downloading.py`).

Two structural problems have accumulated:

1. The shared utility modules have become "junk drawers" — they mix genuinely-generic helpers (used by two or more alarms) with single-consumer, alarm-specific functions that have no other natural home.
2. Each alarm module's `run_alarm()` skeleton duplicates two blocks across alarms: a cron-latency backup block and the entire `state == "CRITICAL"` send sequence.

This feature restructures the codebase so that each alarm owns its alarm-specific code, the shared utilities contain only multi-consumer code, and the duplicated `run_alarm()` skeleton is consolidated — all while preserving the exact runtime behavior of these live alerting pipelines.

This is a **refactoring effort**. The defining constraint is behavior preservation: detection outcomes, sent messages, generated figures, Icinga heartbeats, alarm-history database records, and temporary-file cleanup must be unchanged after the restructure.

## Glossary

- **avo_alarms**: The installable Python package located under `src/avo_alarms`.
- **Alarm_Module**: The current single-file form of an alarm, e.g. `alarm_codes/Infrasound.py`.
- **Alarm_Package**: The target directory form of an alarm, e.g. `alarm_codes/Infrasound/` containing `__init__.py` plus supporting submodules.
- **Shared_Utils**: The top-level utility modules under `utils/` (`processing.py`, `plotting.py`, `downloading.py`, and peers such as `messaging.py`, `alarming.py`, `setup_utils.py`).
- **Dispatcher**: The command-line entry point `scripts/run_alarm.py`, which imports an alarm via `import_module(f"avo_alarms.alarm_codes.{config.alarm_type}")` and calls its `run_alarm`.
- **Run_Alarm_Entry**: The public function each alarm exposes with the signature `run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False)`.
- **Consumer**: An Alarm_Module (or Alarm_Package) that calls a given function.
- **Single_Consumer_Function**: A function called by exactly one alarm.
- **Shared_Function**: A function called by two or more alarms.
- **Litmus_Test**: The classification rule — a function with exactly one Consumer belongs in that alarm's Alarm_Package; a function with two or more Consumers remains in Shared_Utils.
- **Algorithm_Code**: Alarm-specific computational helpers that are not shared, e.g. the Infrasound functions `setup_coordinate_system`, `calc_triggers`, `associator`, `inversion`, `xcorr_align_stream`, `get_target_backazimuth`.
- **Cron_Latency_Backup**: The block guarded by `os.getenv("FROMCRON") == "yep"` that sleeps for, or backs `T0` up by, `config.latency`.
- **Send_Sequence**: The block executed when `state == "CRITICAL"`: rate-limit check via `alarming.can_send`, figure creation in try/except, message creation, Mattermost post in try/except, `messaging.send_alert`, `alarming.record_send`, temporary-file removal via `os.remove`, followed by the Icinga heartbeat.
- **Behavior_Baseline**: The observable outputs of an alarm before the restructure — detection state, message subject/body, figure file, Icinga state and message, database records, and temporary-file cleanup.

## Requirements

### Requirement 1: Preserve the public run_alarm contract

**User Story:** As a maintainer, I want each alarm to keep its existing public entry point, so that the Dispatcher and any external callers continue to work without modification.

#### Acceptance Criteria

1. THE avo_alarms package SHALL expose, for each alarm, a `run_alarm` function callable as `avo_alarms.alarm_codes.{alarm_type}.run_alarm`.
2. THE Run_Alarm_Entry SHALL retain the parameter names and default values `run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False)`.
3. WHEN the Dispatcher calls `import_module(f"avo_alarms.alarm_codes.{config.alarm_type}")` for any existing `alarm_type` value, THE avo_alarms package SHALL return a module that defines `run_alarm`.
4. WHEN the Dispatcher invokes `run_alarm` with the same arguments used before the restructure, THE Run_Alarm_Entry SHALL accept those arguments without raising a `TypeError`.

### Requirement 2: Promote alarm modules to alarm packages

**User Story:** As a maintainer, I want each alarm to be a small package instead of one large file, so that detection, figure, and message code each have a clear home.

#### Acceptance Criteria

1. WHEN an alarm is restructured into an Alarm_Package, THE restructure SHALL create the Alarm_Package directory and its `__init__.py` together as a single change, leaving no Alarm_Package directory without an `__init__.py`.
2. THE Alarm_Package `__init__.py` SHALL define or re-export `run_alarm` so that `avo_alarms.alarm_codes.{alarm_type}` resolves to a module exposing `run_alarm`.
3. WHERE an alarm contains alarm-specific figure code, THE Alarm_Package SHALL place that figure code in a dedicated submodule of the Alarm_Package.
4. WHERE an alarm contains alarm-specific message-construction code, THE Alarm_Package SHALL place that message code in a dedicated submodule of the Alarm_Package.
5. WHERE an alarm contains Algorithm_Code, THE Alarm_Package SHALL place that Algorithm_Code in a dedicated submodule of the Alarm_Package.

### Requirement 3: Classify utility functions using the litmus test

**User Story:** As a maintainer, I want utility functions classified by how many alarms call them, so that ownership is decided by evidence rather than assumption.

#### Acceptance Criteria

1. THE restructure SHALL classify each function in Shared_Utils as either a Single_Consumer_Function or a Shared_Function based on the actual number of distinct alarm Consumers found by call-site analysis.
2. IF a function has exactly one alarm Consumer, THEN THE restructure SHALL classify that function as a Single_Consumer_Function owned by that alarm.
3. IF a function has two or more alarm Consumers, THEN THE restructure SHALL classify that function as a Shared_Function that remains in Shared_Utils.
4. THE restructure SHALL enforce the consumer-count classification strictly and SHALL NOT allow a manual override that contradicts the Litmus_Test result.
5. WHERE call-site analysis contradicts a prior assumption about a function's ownership, THE restructure SHALL use the call-site analysis result. (For example, `addPhaseHint` and `eq_picks_to_dataframe` are called by both Magnitude and Swarm and are therefore Shared_Functions, not Magnitude-only.)

### Requirement 4: Relocate single-consumer functions into their owning alarm package

**User Story:** As a maintainer, I want alarm-specific helpers to live with the alarm that uses them, so that Shared_Utils stops accumulating single-consumer code.

#### Acceptance Criteria

1. WHEN a function is classified as a Single_Consumer_Function, THE restructure SHALL move that function from Shared_Utils into the owning Alarm_Package.
2. WHEN a Single_Consumer_Function is relocated, THE owning alarm SHALL import and call the relocated function from its new location.
3. WHEN a Single_Consumer_Function relocation is completed, THE restructure SHALL verify that the owning alarm successfully imports and calls the function from its new location before treating the relocation as done.
4. WHEN a Single_Consumer_Function is relocated, THE Shared_Utils module that previously contained it SHALL no longer define that function.
5. THE restructure SHALL relocate the NOAA_CIMSS-only functions (`format_cimss_dataframe`, `download_cimss_vv_api`, `scrape_cimss_alert`, `get_cimss_image`), the Pilot_Report-only functions (`pirep_archive_to_dataframe`, `check_volcano_mention`, `download_pilot_reports`), the RSAM-only function (`RSAM_to_DR`), the Lightning-only function (`download_lightning`), the VAA-only function (`download_mesonet_vaa_list`), and the SO2-only function (`download_SO2`) into their respective Alarm_Packages.

### Requirement 5: Keep shared functions in Shared_Utils

**User Story:** As a maintainer, I want genuinely-generic helpers to stay shared, so that multiple alarms keep a single source of truth.

#### Acceptance Criteria

1. WHEN a function is classified as a Shared_Function, THE restructure SHALL retain that function in Shared_Utils regardless of any relocation conflicts or dependency complications encountered.
2. THE restructure SHALL keep multi-consumer functions such as `download_waveforms`, `add_metadata`, `find_nearest_volcano`, `volcano_distance`, `format_timestring`, `post_mattermost`, `send_alert`, `can_send`, `record_send`, `save_file`, `plot_spectrogram`, and `format_spec_xaxis` in Shared_Utils.
3. WHERE a listed Shared_Function is proven to have zero Consumers during the restructure, THE restructure SHALL be permitted to remove that function.
4. WHEN any alarm imports a Shared_Function after the restructure, THE Shared_Utils SHALL resolve that import from its existing module path.

### Requirement 6: Relocate alarm-specific algorithm code out of the alarm entry file

**User Story:** As a maintainer, I want each alarm's algorithm code separated from its run_alarm skeleton, so that the entry file stays small and readable.

#### Acceptance Criteria

1. WHEN an Alarm_Package contains Algorithm_Code, THE restructure SHALL move that Algorithm_Code out of the file that defines `run_alarm` into a dedicated submodule of the Alarm_Package.
2. THE restructure SHALL relocate the Infrasound Algorithm_Code (`setup_coordinate_system`, `calc_triggers`, `associator`, `inversion`, `xcorr_align_stream`, `get_target_backazimuth`) into a dedicated submodule of the Infrasound Alarm_Package.
3. WHEN Algorithm_Code is relocated, THE alarm's `run_alarm` SHALL import and call that Algorithm_Code from its new location.

### Requirement 7: Consolidate the duplicated cron-latency backup block

**User Story:** As a maintainer, I want the cron-latency backup logic defined once, so that the same block is not copied across alarms.

#### Acceptance Criteria

1. THE restructure SHALL provide a single shared implementation of the Cron_Latency_Backup logic.
2. WHEN an alarm previously contained an inline Cron_Latency_Backup block, THE alarm SHALL obtain that behavior from the single shared implementation instead of an inline copy.
3. WHILE `os.getenv("FROMCRON")` equals `"yep"` and `config.latency` is less than 30, THE shared implementation SHALL sleep for `config.latency` seconds.
4. WHILE `os.getenv("FROMCRON")` equals `"yep"` and `config.latency` is 30 or greater, THE shared implementation SHALL back `T0` up by `ceil(config.latency / 60) * 60` seconds.
5. IF `os.getenv("FROMCRON")` does not equal `"yep"`, THEN THE shared implementation SHALL leave `T0` unchanged and SHALL NOT sleep.

### Requirement 8: Consolidate the duplicated critical-state send sequence

**User Story:** As a maintainer, I want the critical-state send sequence defined once, so that alarms share one correct alerting path.

#### Acceptance Criteria

1. THE restructure SHALL provide a single shared implementation of the Send_Sequence.
2. WHEN an alarm reaches `state == "CRITICAL"`, THE alarm SHALL perform alerting through the single shared implementation of the Send_Sequence instead of an inline copy.
3. WHEN the shared Send_Sequence runs, THE shared Send_Sequence SHALL perform, in order: the `alarming.can_send` rate-limit check, figure creation guarded by try/except, message creation, the `messaging.post_mattermost` post guarded by try/except, `messaging.send_alert`, `alarming.record_send`, removal of the generated temporary file via `os.remove`, and the `messaging.icinga` heartbeat.
4. IF `alarming.can_send` returns `False`, THEN THE shared Send_Sequence SHALL skip sending, append the rate-limit note to the state message, send the Icinga heartbeat, and return without calling `send_alert` or `record_send`.
5. IF figure creation raises an exception, THEN THE shared Send_Sequence SHALL log the error and continue with a figure filename value of `None`.
6. WHERE an alarm passes alarm-specific arguments to the Send_Sequence (for example the Infrasound `volcano` target name used by `can_send` and `record_send`), THE shared Send_Sequence SHALL accept and forward those arguments.

### Requirement 9: Preserve alarm runtime behavior (no regressions)

**User Story:** As an operator of live alerting pipelines, I want the restructured alarms to behave identically to before, so that detection and notifications are not disrupted.

#### Acceptance Criteria

1. WHEN an alarm processes a given input for which the Behavior_Baseline produced a specific detection state (`OK`, `WARNING`, or `CRITICAL`), THE restructured alarm SHALL produce the same detection state, and any detection-state mismatch SHALL be treated as a restructure failure regardless of cause.
2. WHEN an alarm reaches `CRITICAL` for a given input, THE restructured alarm SHALL produce the same message subject and body that the Behavior_Baseline produced for that input.
3. WHEN an alarm sends an Icinga heartbeat for a given input, THE restructured alarm SHALL send the same Icinga state and the same state message that the Behavior_Baseline produced for that input.
4. WHEN an alarm records a send for a given input, THE restructured alarm SHALL write the same alarm-history database fields (`alarm_id`, `volcano`, `event_id`, and processed time) that the Behavior_Baseline produced for that input.
5. WHEN an alarm creates and sends a figure for a given input, THE restructured alarm SHALL remove the generated temporary figure file after sending, matching the Behavior_Baseline cleanup.
6. WHEN an error propagates to the Dispatcher, THE restructured alarm SHALL trigger the same Dispatcher error-notification path that the Behavior_Baseline produced.
7. IF no error propagates to the Dispatcher for a given input, THEN THE restructured alarm SHALL NOT trigger the Dispatcher error-notification path.

### Requirement 10: Preserve configuration compatibility

**User Story:** As an operator, I want existing config files to keep working unchanged, so that I do not have to edit deployment configuration.

#### Acceptance Criteria

1. THE restructure SHALL keep the existing `.py` config modules loaded from `CONFIGS_DIR` unchanged, preserving the `load_config` contract that reads and execs `CONFIGS_DIR/{config_name}.py`.
2. WHEN `load_config` reads `CONFIGS_DIR/{config_name}.py`, resolves its `alarm_type`, and the Dispatcher calls `import_module(f"avo_alarms.alarm_codes.{alarm_type}")`, THE avo_alarms package SHALL resolve that module to the alarm's Run_Alarm_Entry.
3. THE restructure SHALL continue to read alarm metadata through `utils/setup_utils.py` (including `load_config`, `load_volcano_list`, and `update_infrasound_config`) without changing their public call signatures.

### Requirement 11: Maintain import integrity

**User Story:** As a maintainer, I want all imports to resolve after the restructure, so that the package loads and runs without import errors.

#### Acceptance Criteria

1. WHEN the avo_alarms package is imported, THE avo_alarms package SHALL load without raising `ImportError` or `ModuleNotFoundError`.
2. THE restructure SHALL NOT introduce circular imports between Alarm_Packages and Shared_Utils.
3. WHEN a function is relocated, THE restructure SHALL update every reference to that function so that no Consumer imports it from a path where it no longer exists.
4. IF a relocated Single_Consumer_Function is later referenced by a second alarm, THEN THE restructure SHALL treat the function as a Shared_Function per the Litmus_Test rather than importing it across Alarm_Packages.

### Requirement 12: Verify behavior preservation through tests

**User Story:** As a maintainer, I want the restructure validated by tests, so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE restructure SHALL include tests that exercise each restructured alarm's `run_alarm` with external side effects (data download, Mattermost, email, Icinga, database) replaced by test doubles.
2. WHEN a restructured alarm is run against a recorded input, THE test suite SHALL assert that the resulting detection state matches the Behavior_Baseline state for that input.
3. WHEN a restructured alarm reaches `CRITICAL` against a recorded input, THE test suite SHALL assert that the message subject and body match the Behavior_Baseline message for that input.
4. WHEN the shared Cron_Latency_Backup and Send_Sequence implementations are tested, THE test suite SHALL assert the ordering and conditional branches defined in Requirements 7 and 8.
