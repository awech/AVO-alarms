# Requirements Document

## Introduction

This feature migrates the alarm system's per-alarm configuration from executable
Python modules (`config/{name}.py`, loaded by `exec`) to declarative YAML
(`config/{name}.yml`, parsed with `yaml.safe_load`). The migration adopts the
already-restructured lowercase/snake-case YAML schema as canonical and refactors
each alarm package to read that schema directly, rather than hiding a
compatibility adapter inside the loader. The cutover is a hard switch: after
migration the loader reads only `.yml`, the second config consumer
(`download_station_xml`) is migrated, the test harness is updated, the frozen
golden baselines are re-captured, and the `config/*.py` modules are deleted.

The migration preserves the runtime behavior the alarm code depends on — the
top-level path-string→`pathlib.Path` conversion, the Infrasound target
enrichment, and the NSLC/threshold values that drive detection — and preserves
the public signature of `load_config`. The only intentional behavioral change is
the per-station ordering of the RSAM heartbeat string, which the restructured
schema implies and which is captured in a re-frozen baseline.

## Glossary

- **Loader**: The `setup_utils.load_config` function that reads a single alarm's
  configuration from `CONFIGS_DIR` and returns a config object.
- **Config_Object**: The object returned by the Loader. After migration it is a
  `types.SimpleNamespace` whose top-level YAML keys are exposed as attributes,
  with nested values left as native YAML `list`/`dict`/scalar types.
- **Canonical_Schema**: The restructured lowercase/snake-case YAML schema already
  present in `config/*.yml`, adopted by this migration as the authoritative
  config format.
- **Infrasound_Enricher**: The `setup_utils.update_infrasound_config` function
  that fills `lat`/`lon` and default `vmin`/`vmax` on Infrasound targets.
- **Volcano_List**: The DataFrame returned by `setup_utils.load_volcano_list`
  containing `Name`, `Latitude`, and `Longitude` columns.
- **Path_Predicate**: The existing `looks_like_path` predicate that identifies
  scalar strings that should be converted to `pathlib.Path`.
- **Station_Metadata_Downloader**: The `downloading.download_station_xml`
  function that collects the union of NSLC across seismic alarms and writes
  `STATION_XML`.
- **NSLC**: A Network.Station.Location.Channel identifier string (e.g.
  `AV.SDPI.01.HDF`).
- **Sentinel_Value**: The numeric value (`1e7`) assigned to plot-only infrasound
  channels in the RSAM stations list so they never exceed the detection
  threshold.
- **Arrestor**: The RSAM station whose quiescence is required for a detection;
  it must remain the last entry in the reconstructed RSAM stations list.
- **Behavior_Baselines**: The frozen golden JSON files in
  `tests/alarms/baselines/` that capture each alarm's `run_alarm` output for the
  behavior-preservation suite.
- **Verify_Only_Alarm**: An alarm (Lightning, NOAA_CIMSS, Pilot_Report/PIREP,
  SO2, VAA) whose consumers already read lowercase/snake keys and require no
  code-read changes, only verification against its `.yml`.
- **Restructure_Spec**: The `alarm-modules-restructure` spec whose Requirement 10
  freezes the `.py`-based `load_config` contract that this migration supersedes.

## Requirements

### Requirement 1: YAML-based configuration loading

**User Story:** As a developer maintaining the alarm system, I want each alarm's
configuration loaded from declarative YAML, so that configuration is data rather
than executable code while the loader contract stays stable.

#### Acceptance Criteria

1. WHEN the Loader is called with a config name, THE Loader SHALL read
   `CONFIGS_DIR/{config_name}.yml` and parse it with `yaml.safe_load`.
2. WHEN the Loader parses a config file, THE Loader SHALL return a
   `SimpleNamespace` whose top-level YAML mapping keys are exposed as attributes.
3. WHERE a top-level YAML value is a nested list or dict, THE Loader SHALL leave
   that value as the native parsed YAML type without conversion.
4. THE Loader SHALL accept a single `config_name` string argument and return a
   single Config_Object, preserving the existing public call signature.
5. WHEN attribute access is performed on the Config_Object, THE Config_Object
   SHALL support `getattr` and `hasattr` for top-level keys.
6. WHERE a Config_Object is constructed independently of the Loader (for example
   in tests), THE Config_Object SHALL remain a valid config object without
   requiring the Loader to have been called.

### Requirement 2: Top-level path-string conversion

**User Story:** As a developer, I want path-like configuration strings converted
to `pathlib.Path`, so that downstream code keeps the same path semantics it had
under the Python config modules.

#### Acceptance Criteria

1. WHEN the Loader processes a top-level scalar string that satisfies the
   Path_Predicate, THE Loader SHALL replace that attribute value with a
   `pathlib.Path` constructed from the string.
2. WHERE a top-level scalar string does not satisfy the Path_Predicate, THE
   Loader SHALL leave that value as the original string.
3. WHERE a string appears inside a nested list or dict value, THE Loader SHALL
   leave that string unconverted.
4. WHEN the Loader completes path conversion, THE Loader SHALL preserve the set
   of top-level keys without adding or removing any key.

### Requirement 3: Infrasound target enrichment

**User Story:** As an operator running the Infrasound alarm, I want each target
enriched with location and velocity defaults, so that detection has the
coordinates and velocity bounds it requires.

#### Acceptance Criteria

1. WHEN the Loader loads a config whose `alarm_type` equals `Infrasound`, THE
   Loader SHALL invoke the Infrasound_Enricher on the Config_Object.
2. THE Infrasound_Enricher SHALL read targets from `config.targets`.
3. IF a target lacks `lat` or `lon`, THEN THE Infrasound_Enricher SHALL fill
   `lat` and `lon` from the Volcano_List row matching the target `name`.
4. IF a target lacks `vmin`, THEN THE Infrasound_Enricher SHALL set `vmin` from
   the `INFRASOUND_VMIN` environment variable, defaulting to `0.28`.
5. IF a target lacks `vmax`, THEN THE Infrasound_Enricher SHALL set `vmax` from
   the `INFRASOUND_VMAX` environment variable, defaulting to `0.45`.
6. WHERE a target already has `lat`, `lon`, `vmin`, or `vmax`, THE
   Infrasound_Enricher SHALL preserve the existing value.
7. THE Infrasound_Enricher SHALL accept a single Config_Object argument and
   return a Config_Object, preserving its existing public call signature.

### Requirement 4: RSAM alarm refactor to canonical schema

**User Story:** As a developer, I want the RSAM alarm to read the split station
schema, so that RSAM detection works against the canonical YAML without a loader
adapter.

#### Acceptance Criteria

1. THE RSAM alarm code SHALL read seismic stations from `config.rsam_stations`,
   plot-only infrasound channels from `config.infrasound`, and the arrestor from
   `config.arrestor`.
2. WHEN the RSAM alarm builds its ordered station list, THE RSAM alarm code SHALL
   place all `rsam_stations` entries first, then the `infrasound` channels, then
   the Arrestor as the final entry.
3. WHEN the RSAM alarm adds an `infrasound` channel to the station list, THE RSAM
   alarm code SHALL assign that channel the Sentinel_Value so it never exceeds the
   detection threshold.
4. THE RSAM alarm code SHALL read the volcano name from `config.volcano_name`.
5. WHEN the RSAM alarm evaluates detection over the reconstructed station list,
   THE RSAM alarm code SHALL produce the same detection outcome as the Python
   configuration produced for equivalent input data.

### Requirement 5: Infrasound alarm refactor to canonical schema

**User Story:** As a developer, I want the Infrasound alarm to read plain NSLC
strings and lowercase target keys, so that it consumes the canonical YAML
directly.

#### Acceptance Criteria

1. THE Infrasound alarm code SHALL read its station identifiers from
   `config.nslc` as a list of NSLC strings.
2. THE Infrasound alarm code SHALL read its targets from `config.targets`.
3. WHEN the Infrasound alarm reads `config.nslc`, THE Infrasound alarm code SHALL
   treat each element as a string rather than a mapping.

### Requirement 6: Tremor alarm refactor and grid reconstruction

**User Story:** As a developer, I want the Tremor alarm to read plain NSLC
strings and rebuild its search grid from scalar bounds, so that it consumes the
canonical YAML while producing the same grid arrays as before.

#### Acceptance Criteria

1. THE Tremor alarm code SHALL read its station identifiers from `config.nslc` as
   a list of NSLC strings.
2. WHEN the Tremor alarm builds its search grid, THE Tremor alarm code SHALL
   construct longitude, latitude, and depth arrays from the `config.grid` scalar
   bounds and steps.
3. WHEN the Tremor alarm reconstructs each grid array, THE Tremor alarm code SHALL
   produce arrays equal to the arrays the Python `grid` definition produced, using
   `arange(min, max + 0.001, step)` for longitude, latitude, and depth.

### Requirement 7: Magnitude alarm refactor to lowercase keys

**User Story:** As a developer, I want the Magnitude alarm to read lowercase
threshold keys, so that it consumes the canonical YAML directly.

#### Acceptance Criteria

1. THE Magnitude alarm code SHALL read `config.magmin`, `config.maxdep`,
   `config.distance`, and `config.duration` from the Config_Object.
2. WHEN the Magnitude alarm evaluates detection, THE Magnitude alarm code SHALL
   use the same threshold values that the Python configuration supplied.

### Requirement 8: Swarm alarm refactor to lowercase and nested snake-case keys

**User Story:** As a developer, I want the Swarm alarm to read lowercase
thresholds and snake-case nested parameters, so that it consumes the canonical
YAML directly and the latent parameter-name typo is resolved.

#### Acceptance Criteria

1. THE Swarm alarm code SHALL read `config.magmin`, `config.maxdep`, and
   `config.volcano_distance` from the Config_Object.
2. THE Swarm alarm code SHALL read nested swarm parameters using the snake-case
   keys `name`, `max_evt_distance`, `max_evt_time`, and `min_num_evt` from each
   entry of `config.swarm_parameters`.
3. THE Swarm alarm code SHALL read the swarm-cluster name from the `name` key for
   every entry in `config.swarm_parameters`.

### Requirement 9: Verify-only alarms remain unchanged

**User Story:** As a developer, I want the alarms that already use lowercase
keys verified against their YAML, so that no unnecessary code changes are made
and their behavior is confirmed preserved.

#### Acceptance Criteria

1. WHERE an alarm is a Verify_Only_Alarm, THE migration SHALL load that alarm's
   configuration through the Loader without changing the alarm's config-read
   code.
2. WHEN a Verify_Only_Alarm is loaded from its `.yml`, THE Config_Object SHALL
   expose every attribute that the alarm's consumers read.

### Requirement 10: Station metadata downloader migration

**User Story:** As an operator refreshing station metadata, I want the downloader
to read the YAML configs, so that station XML reflects the canonical schema after
the `.py` modules are removed.

#### Acceptance Criteria

1. WHEN the Station_Metadata_Downloader collects configuration files, THE
   Station_Metadata_Downloader SHALL glob `CONFIGS_DIR` for the RSAM, Tremor, and
   Infrasound `*.yml` files.
2. WHEN the Station_Metadata_Downloader reads the RSAM config, THE
   Station_Metadata_Downloader SHALL extract NSLC from `rsam_stations[*].nslc`,
   `infrasound[*]`, and `arrestor.nslc`.
3. WHEN the Station_Metadata_Downloader reads the Tremor or Infrasound config, THE
   Station_Metadata_Downloader SHALL extract NSLC from `nslc[*]` as plain strings.
4. WHEN the Station_Metadata_Downloader has collected NSLC across the seismic
   alarms, THE Station_Metadata_Downloader SHALL write `STATION_XML` from the
   de-duplicated union of those NSLC.
5. THE Station_Metadata_Downloader SHALL preserve its existing public call
   signature.

### Requirement 11: Pre-cutover value parity check

**User Story:** As a developer performing the migration, I want each `.py` config
compared against its `.yml` before deletion, so that accidental value drift is
caught before it is locked into the re-frozen baselines.

#### Acceptance Criteria

1. WHEN preparing to delete a `.py` config module, THE migration SHALL compare
   the configuration values produced by the `.py` module against the values
   produced by the corresponding `.yml` file under the Canonical_Schema.
2. IF the parity check finds a value difference that is not an intended schema
   restructuring, THEN THE migration SHALL surface the difference for review
   before deletion proceeds.
3. WHERE a difference is an intended schema restructuring documented in the
   design, THE migration SHALL record that difference as expected rather than as
   drift.

### Requirement 12: Hard cutover and removal of Python config modules

**User Story:** As a developer, I want the Python config modules removed after
migration, so that YAML is the single source of configuration with no dual
maintenance.

#### Acceptance Criteria

1. WHEN the Loader, the Station_Metadata_Downloader, the alarm code refactors, and
   the parity check are complete, THE migration SHALL delete the `config/*.py`
   configuration modules.
2. WHEN the Loader's own refactor to YAML is complete, THE Loader SHALL read
   configuration exclusively from `.yml` files, regardless of whether the other
   refactors are complete.

### Requirement 13: Test harness update and baseline re-freeze

**User Story:** As a developer, I want the behavior-preservation test harness
updated and the golden baselines re-frozen, so that the suite validates the new
loader and schema and documents the one intentional message change.

#### Acceptance Criteria

1. THE `tests/alarms/conftest.py` module docstring SHALL be updated to remove the
   note stating that `.yml` files are not consumed.
2. WHEN the test harness loads alarm configurations, THE test harness SHALL load
   them through the Loader reading `.yml` files.
3. WHEN the loader and schema refactors are complete, THE migration SHALL
   re-freeze the Behavior_Baselines in `tests/alarms/baselines/`.
4. WHERE an alarm other than RSAM has its baseline re-frozen, THE re-frozen
   baseline content SHALL be unchanged from the prior baseline content.
5. WHERE the RSAM baseline is re-frozen, THE re-frozen baseline SHALL reflect the
   changed per-station ordering of the RSAM heartbeat string as the only
   intentional message-text change in the migration.
6. WHEN the behavior-preservation suite runs against the re-frozen baselines, THE
   suite SHALL pass for every alarm.

### Requirement 14: Configuration error handling

**User Story:** As an operator, I want configuration errors surfaced clearly, so
that misconfiguration fails in an understandable way rather than producing a
partial config object.

#### Acceptance Criteria

1. IF `CONFIGS_DIR/{config_name}.yml` does not exist, THEN THE Loader SHALL
   propagate a `FileNotFoundError` identifying the resolved path.
2. IF a config file is not valid YAML or its root is not a mapping, THEN THE
   Loader SHALL propagate an error and SHALL NOT return a partial Config_Object.
3. IF an alarm reads a configuration key absent from the Config_Object, THEN THE
   Config_Object SHALL raise `AttributeError` on that attribute access.
4. IF an Infrasound target name is absent from the Volcano_List and the target
   lacks explicit `lat`/`lon`, THEN THE Infrasound_Enricher SHALL raise an error
   during enrichment.

### Requirement 15: Coordination with the alarm-modules-restructure spec

**User Story:** As a developer coordinating two active specs, I want this
migration to deliberately supersede the restructure's frozen config contract and
land after it, so that the same files are not churned twice and baselines are not
invalidated mid-flight.

#### Acceptance Criteria

1. THE migration SHALL preserve the public `load_config(config_name)` signature so
   the dispatcher contract defined by the Restructure_Spec continues to hold.
2. WHERE the Restructure_Spec Requirement 10 freezes the `.py`-based loader
   contract, THE migration SHALL supersede that decision by switching the loader
   to `.yml`.
3. THE migration SHALL be sequenced to land after, or in coordination with, the
   Restructure_Spec to avoid invalidating that spec's golden baselines mid-flight.
