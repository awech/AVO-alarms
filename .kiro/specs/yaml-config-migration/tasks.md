# Implementation Plan: YAML Config Migration

## Overview

This plan migrates per-alarm configuration from executable `config/{name}.py`
modules to declarative `config/{name}.yml`, refactors `setup_utils.load_config`
to parse YAML into a `SimpleNamespace`, refactors each alarm package to read the
canonical lowercase/snake-case schema, migrates `download_station_xml`, runs a
pre-cutover value-parity check, performs the hard cutover (deleting `config/*.py`),
and re-freezes the golden behavior baselines. Implementation language is Python
(`yaml.safe_load`; `pyyaml` and `python-dotenv` are existing dependencies).

Run all Python/test commands with the conda environment binary:
`/home/awech/.conda/envs/dev-alarms/bin/python`.

> Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP.
> Each task references specific requirement clauses for traceability. Property
> tests reference the numbered Correctness Properties from the design document.

## Tasks

- [x] 1. Refactor the loader to parse YAML
  - [x] 1.1 Rewrite `setup_utils.load_config` for YAML
    - Read `CONFIGS_DIR/{config_name}.yml` and parse with `yaml.safe_load`
    - Wrap the parsed dict in `types.SimpleNamespace` (top-level attribute access)
    - Convert top-level scalar path-like strings to `pathlib.Path` (reuse existing `looks_like_path`); leave nested list/dict members untouched
    - Dispatch to `update_infrasound_config` when `alarm_type == "Infrasound"`
    - Preserve the `load_config(config_name)` public signature
    - Propagate `FileNotFoundError` (with resolved path) and YAML/root-not-mapping errors without returning a partial object
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 14.1, 14.2, 14.3, 15.1_

  - [ ]* 1.2 Write property test for top-level path conversion
    - **Property 1: Top-level path-conversion invariant**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 1.3**
    - Use Hypothesis to generate top-level mappings; assert path-like scalars become `Path`, others unchanged, nested strings untouched, key set preserved, conversion idempotent

  - [ ]* 1.3 Write unit tests for loader error handling
    - Missing `.yml` raises `FileNotFoundError` with resolved path; malformed/non-mapping YAML raises without partial object; missing attribute raises `AttributeError`
    - _Requirements: 14.1, 14.2, 14.3_

  - [x] 1.4 Update `update_infrasound_config` to canonical keys
    - Read targets from `config.targets` (was `config.TARGETS`)
    - Fill `lat`/`lon` from the Volcano_List row matching target `name` when absent
    - Default `vmin`/`vmax` from `INFRASOUND_VMIN`/`INFRASOUND_VMAX` env (`0.28`/`0.45`); preserve pre-existing values
    - Raise during enrichment when a target name is absent from the Volcano_List and lacks explicit `lat`/`lon`
    - Preserve the single-Config_Object signature
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 14.4_

  - [ ]* 1.5 Write property test for Infrasound enrichment completeness
    - **Property 3: Infrasound enrichment completeness**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
    - Use Hypothesis to generate target lists; assert every target ends with `lat`/`lon`/`vmin`/`vmax`, pre-existing values preserved, env defaults applied

- [x] 2. Checkpoint - loader functioning
  - Ensure all loader tests pass, ask the user if questions arise.

- [x] 3. Refactor RSAM alarm to canonical schema
  - [x] 3.1 Reconstruct RSAM station list and rename volcano key
    - In `RSAM/__init__.py`, build the ordered station list from `config.rsam_stations` first, then `config.infrasound` channels (each assigned Sentinel_Value `1e7`), then `config.arrestor` last
    - Read the volcano name from `config.volcano_name` (was `config.VOLCANO_NAME`); update `figure.py` and `message.py` reads accordingly
    - Keep detection logic (`rms[-1] < lvlv[-1]`, `sum(rms[:-1] > lvlv[:-1]) >= min_sta`) unchanged
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 3.2 Write property test for RSAM NSLC-extraction set invariant
    - **Property 2: RSAM NSLC-extraction set invariant**
    - **Validates: Requirements 4.1, 4.2, 4.3, 10.2**
    - Use Hypothesis to generate RSAM-shaped configs; assert extracted NSLC set equals union of `rsam_stations.nslc`, `infrasound`, `arrestor.nslc`; arrestor last; infrasound channels carry the sentinel

- [x] 4. Refactor Infrasound alarm to canonical schema
  - [x] 4.1 Read plain `nslc` strings and `targets`
    - In `Infrasound/__init__.py`, `detection.py`, `figure.py`, `message.py`, read station identifiers from `config.nslc` as a list of strings (was list of `{nslc}` dicts) and targets from `config.targets` (was `config.TARGETS`)
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 4.2 Write unit tests for Infrasound config reads
    - Assert `config.nslc` elements are strings and `config.targets` enriched entries are consumed correctly
    - _Requirements: 5.1, 5.3_

- [x] 5. Refactor Tremor alarm to canonical schema
  - [x] 5.1 Read plain `nslc` strings and rebuild grid from scalars
    - In `Tremor/__init__.py`, `detection.py`, `figure.py`, read station identifiers from `config.nslc` as a list of strings (was list of `{nslc,lat,lon}` dicts)
    - Build longitude, latitude, and depth arrays via `arange(min, max + 0.001, step)` from `config.grid` scalar bounds/steps
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 5.2 Write property test for Tremor grid arange equality
    - **Property 4: Tremor grid `arange` array equality**
    - **Validates: Requirements 6.2, 6.3**
    - Use Hypothesis to generate grid scalar bounds/steps; assert reconstructed arrays equal `arange(min, max + 0.001, step)` per dimension

- [x] 6. Refactor Magnitude alarm to lowercase keys
  - [x] 6.1 Read lowercase threshold keys
    - In `Magnitude/__init__.py`, `detection.py`, read `config.magmin`, `config.maxdep`, `config.distance`, `config.duration` (were UPPERCASE)
    - _Requirements: 7.1, 7.2_

  - [ ]* 6.2 Write unit tests for Magnitude threshold reads
    - Assert detection uses the same threshold values the `.py` config supplied
    - _Requirements: 7.2_

- [x] 7. Refactor Swarm alarm to lowercase and snake-case nested keys
  - [x] 7.1 Read lowercase thresholds and snake-case swarm parameters
    - In `Swarm/__init__.py`, `detection.py`, read `config.magmin`, `config.maxdep`, `config.volcano_distance` (were UPPERCASE)
    - Read nested `config.swarm_parameters` entries using snake-case keys `name`, `max_evt_distance`, `max_evt_time`, `min_num_evt`; read the cluster name from `name` for every entry (resolves the latent `Number` typo)
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ]* 7.2 Write unit tests for Swarm parameter reads
    - Assert nested snake-case keys resolve and `name` is read for every entry
    - _Requirements: 8.2, 8.3_

- [x] 8. Verify the verify-only alarms against their YAML
  - [x] 8.1 Confirm Lightning, NOAA_CIMSS, Pilot_Report, SO2, VAA load cleanly
    - Load each via `setup_utils.load_config` and confirm every attribute the consumers read (`config.dist1`, `config.dist2`, `config.duration`, `config.max_distance`, `config.mattermost_channel_id`, `config.ignore_volcanoes`, `getattr(config, "max_distance", 25)`, etc.) resolves; make no config-read code changes
    - _Requirements: 9.1, 9.2_

- [x] 9. Checkpoint - all alarm refactors complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Migrate the station metadata downloader
  - [x] 10.1 Glob `.yml` and extract NSLC per canonical schema
    - In `utils/downloading.py`, glob `CONFIGS_DIR` for RSAM/Tremor/Infrasound `*.yml` (not `*.py`) and `yaml.safe_load` each
    - Extract NSLC: RSAM from `rsam_stations[*].nslc` + `infrasound[*]` + `arrestor.nslc`; Tremor and Infrasound from `nslc[*]` plain strings
    - Write `STATION_XML` from the de-duplicated union; preserve the `download_station_xml()` signature
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 10.2 Write integration test for downloader NSLC union
    - Use a temp `CONFIGS_DIR` with representative `.yml` and a mocked IRIS client; assert the `.yml` glob + de-duplicated NSLC union
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 11. Pre-cutover value-parity check
  - [x] 11.1 Compare each `.py`-produced config against its `.yml`-produced config
    - For each alarm, load values from the `.py` module and from the `.yml` under the canonical schema and diff them
    - Surface unexpected value drift for review; record intended schema restructurings (lowercase/snake keys, RSAM station split, Infrasound plain `nslc`, `targets`, Tremor grid scalars, Swarm `name` typo fix) as expected
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 12. Hard cutover - remove Python config modules
  - [x] 12.1 Delete `config/*.py` after loader/downloader/refactors/parity-check complete
    - Confirm the loader reads exclusively from `.yml`, then delete the `config/*.py` modules
    - _Requirements: 12.1, 12.2, 15.2, 15.3_

- [x] 13. Update test harness and re-freeze baselines
  - [x] 13.1 Update conftest docstring and confirm `.yml` loading
    - In `tests/alarms/conftest.py`, update the module docstring to drop the "`.yml` not consumed" note; ensure configs load through `setup_utils.load_config` reading `.yml` (no env changes; `CONFIGS_DIR` still points at `config/`)
    - _Requirements: 13.1, 13.2_

  - [x] 13.2 Re-freeze golden baselines
    - Re-capture `tests/alarms/baselines/*.json` after the loader + schema refactor; RSAM heartbeat per-station ordering is the only intentional change; all other baselines unchanged in content
    - _Requirements: 13.3, 13.4, 13.5_

  - [ ]* 13.3 Run the behavior-preservation suite against re-frozen baselines
    - Run with `/home/awech/.conda/envs/dev-alarms/bin/python`; assert every alarm's `run_alarm` output matches the re-frozen baselines
    - _Requirements: 13.6_

- [x] 14. Final checkpoint - full suite green
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (unit/property/integration tests) and can be skipped for a faster MVP.
- Each task references specific requirement clauses for traceability.
- Property tests (Hypothesis) validate the universal Correctness Properties from the design; unit/integration tests cover examples and edge cases.
- Run every Python and test command with `/home/awech/.conda/envs/dev-alarms/bin/python` per the workspace environment rule.
- This migration is sequenced to land after / in coordination with `alarm-modules-restructure` (Requirement 15); the `load_config(config_name)` signature is preserved throughout.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4"] },
    { "id": 2, "tasks": ["1.5", "3.1", "4.1", "5.1", "6.1", "7.1", "8.1"] },
    { "id": 3, "tasks": ["3.2", "4.2", "5.2", "6.2", "7.2", "10.1"] },
    { "id": 4, "tasks": ["10.2", "11.1"] },
    { "id": 5, "tasks": ["12.1"] },
    { "id": 6, "tasks": ["13.1"] },
    { "id": 7, "tasks": ["13.2"] },
    { "id": 8, "tasks": ["13.3"] }
  ]
}
```
