"""Pydantic v2 schemas for validating alarm YAML configuration files.

Each alarm type has a dedicated model describing the fields the alarm code
expects. The :data:`SCHEMAS` registry maps the ``alarm_type`` discriminator
found in every config to the model that should validate it.

Required-vs-optional is driven by what the alarm *code* actually needs at
runtime, not merely by what the example ``config/*.yml`` files happen to show:

* A field is REQUIRED only when the alarm code reads it bare (``config.x``) with
  no ``getattr`` default, no ``hasattr`` guard, and no fallback applied in
  ``setup_utils.load_config`` / ``update_infrasound_config``.
* A field is OPTIONAL when the code guards it, defaults it, or sources it from
  an environment variable.

``extra="forbid"`` is used throughout so typos (``aler_memory`` instead of
``alert_memory``) surface as validation errors instead of silently doing
nothing at runtime. A handful of keys appear in the shipped example configs but
are never read by the code (noted inline as "unused by code"); they are
declared as optional fields so real files validate while typos still fail.

Entry points:
    validate_config(path)        -> validate a single YAML file
    validate_config_dir(dir)     -> validate every alarm *.yml in a directory
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

# A numeric value that may be written as a string arithmetic expression
# (e.g. "2 * 3600", "350/100"); setup_utils evaluates these at load time.
Number = Union[int, float]
NumberOrExpr = Union[int, float, str]


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class AlarmConfigBase(BaseModel):
    """Fields common to every alarm config.

    ``alarm_type`` selects which concrete model validates the file;
    ``alarm_name`` is the human-readable name used in alerts and as the
    distribution-list key. Both are required by every alarm code path.

    The remaining shared fields are optional:
    * ``alert_memory`` / ``max_alerts`` gate rate-limiting and only take effect
      when both are set (``alarming.can_send``).
    * ``mattermost_channel_id`` / ``icinga_service_name`` fall back to defaults
      in ``messaging``.
    * ``mm_response_channels`` maps volcano name -> Mattermost channel id.
    * ``kill`` is the run_alarm kill switch, allowed on any config.
    """

    model_config = ConfigDict(extra="forbid")

    alarm_type: str
    alarm_name: str
    alert_memory: Union[Number, None] = None
    max_alerts: Union[int, None] = None
    mattermost_channel_id: Union[str, None] = None
    icinga_service_name: Union[str, None] = None
    mm_response_channels: Union[dict[str, str], None] = None
    kill: Union[bool, None] = None
    # Present in some shipped configs (e.g. SO2) but not read by the alarm
    # code, which hardcodes its image paths. Allowed so real files validate.
    img_file: Union[str, None] = None


# ---------------------------------------------------------------------------
# Nested structures
# ---------------------------------------------------------------------------


class RsamStation(BaseModel):
    """One entry in an RSAM ``rsam_stations`` list. Both fields required."""

    model_config = ConfigDict(extra="forbid")

    nslc: str
    value: NumberOrExpr


class Arrestor(BaseModel):
    """RSAM ``arrestor`` station. Both fields required."""

    model_config = ConfigDict(extra="forbid")

    nslc: str
    value: NumberOrExpr


class InfrasoundChannelMeta(BaseModel):
    """Per-channel metadata when Infrasound ``nslc`` is given as a dict.

    When ``nslc`` is a mapping instead of a plain list, the alarm reads
    ``lat``/``lon``/``gain`` for each channel directly, so all three are
    required for that form.
    """

    model_config = ConfigDict(extra="forbid")

    lat: Number
    lon: Number
    gain: Number


class InfrasoundTarget(BaseModel):
    """One Infrasound ``targets`` entry.

    ``name``, ``az_tolerance`` and ``min_pa`` are read bare by the detection
    code; the rest are filled from the volcano list or environment defaults in
    ``update_infrasound_config`` when absent.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    az_tolerance: Number
    min_pa: Number
    lat: Union[Number, None] = None
    lon: Union[Number, None] = None
    vmin: Union[Number, None] = None
    vmax: Union[Number, None] = None
    cmin: Union[Number, None] = None
    back_azimuth: Union[Number, None] = None
    local_nslc: Union[list[str], None] = None
    plot_duration: Union[NumberOrExpr, None] = None
    traveltime: Union[bool, None] = None
    array_label: Union[str, None] = None


class TremorGrid(BaseModel):
    """Tremor search ``grid``. All nine bounds are read bare by build_grid."""

    model_config = ConfigDict(extra="forbid")

    lon_min: float
    lon_max: float
    lon_step: float
    lat_min: float
    lat_max: float
    lat_step: float
    depth_min: float
    depth_max: float
    depth_step: float


class SwarmParameter(BaseModel):
    """One Swarm ``swarm_parameters`` entry. All four fields read bare."""

    model_config = ConfigDict(extra="forbid")

    name: str
    max_evt_distance: Number
    max_evt_time: Number
    min_num_evt: int


# ---------------------------------------------------------------------------
# Per-alarm models
# ---------------------------------------------------------------------------


class RSAMConfig(AlarmConfigBase):
    """RSAM alarm.

    ``duration``/``taper``/``latency`` are defaulted in load_config;
    ``volcano_name``/``infrasound``/``plot_duration`` are guarded in the code.
    """

    rsam_stations: list[RsamStation]
    arrestor: Arrestor
    f1: Number
    f2: Number
    min_sta: int
    duration: Union[NumberOrExpr, None] = None
    taper: Union[Number, None] = None
    latency: Union[Number, None] = None
    plot_duration: Union[NumberOrExpr, None] = None
    infrasound: Union[list[str], str, None] = None
    volcano_name: Union[str, None] = None


class TremorConfig(AlarmConfigBase):
    """Tremor alarm.

    ``rsam_station``/``rsam_threshold`` are gated by hasattr in run_alarm, but
    ``create_icinga_test`` splits ``rsam_station`` unconditionally, so it is
    effectively required on the normal status path; both are kept optional to
    match the guard but are present in every real config.
    ``lookback_window``/``window_length``/``grid_file``/``latency``/``taper``
    are defaulted in load_config.
    """

    nslc: list[str]
    volcano: str
    threshold: Number
    f1: Number
    f2: Number
    highpass: Number
    lowpass: Number
    min_sta: int
    Cmin: Number
    Cmax: Number
    bstrap: int
    bstrap_prct: Number
    max_scatter: Number
    grid: TremorGrid
    phase_list: list[str]
    rsam_station: Union[str, None] = None
    rsam_threshold: Union[Number, None] = None
    lookback_window: Union[Number, None] = None
    window_length: Union[NumberOrExpr, None] = None
    grid_file: Union[str, None] = None
    latency: Union[Number, None] = None
    taper: Union[Number, None] = None


class InfrasoundConfig(AlarmConfigBase):
    """Infrasound alarm.

    ``nslc`` may be a plain list of channel strings, or a dict mapping each
    channel to per-channel metadata (``lat``/``lon``/``gain``). ``targets`` and
    ``min_chan`` are read bare; ``f1``/``f2`` feed preprocessing.

    ``min_cc`` and ``cc_shift_length`` ship in the example config but are not
    read by the current code (declared here so real files validate).
    ``duration``/``taper``/``latency`` and the ``lts_*``/``min_channels``/
    ``max_gap_fraction`` family are defaulted in load_config /
    update_infrasound_config.
    """

    nslc: Union[list[str], dict[str, Union[InfrasoundChannelMeta, None]]]
    f1: Number
    f2: Number
    min_chan: int
    targets: list[InfrasoundTarget]
    # Present in example config but unused by code:
    min_cc: Union[Number, None] = None
    cc_shift_length: Union[Number, None] = None
    # Optional / defaulted:
    duration: Union[Number, None] = None
    taper: Union[Number, None] = None
    latency: Union[Number, None] = None
    min_channels: Union[int, None] = None
    max_gap_fraction: Union[Number, None] = None
    lts_window_length: Union[Number, None] = None
    lts_overlap: Union[Number, None] = None
    lts_alpha: Union[Number, None] = None
    lts_n_samples: Union[int, None] = None
    plotchan: Union[str, None] = None


class LightningConfig(AlarmConfigBase):
    """Lightning alarm. ``ignore_volcanoes`` is optional."""

    dist1: Number
    dist2: Number
    duration: NumberOrExpr
    ignore_volcanoes: Union[list[str], None] = None


class MagnitudeConfig(AlarmConfigBase):
    """Magnitude alarm. Map-extent fields are getattr-defaulted in figure."""

    magmin: Number
    maxdep: Number
    distance: Number
    duration: NumberOrExpr
    map_distance: Union[Number, None] = None
    inset_map_distance: Union[Number, None] = None


class SwarmConfig(AlarmConfigBase):
    """Swarm alarm.

    ``magmin`` ships in the example config but is not read by the Swarm code
    path (download uses only ``maxdep``); declared so real files validate.
    """

    maxdep: Number
    volcano_distance: Number
    swarm_parameters: list[SwarmParameter]
    magmin: Union[Number, None] = None  # present in example, unused by code
    map_distance: Union[Number, None] = None


class NOAACIMSSConfig(AlarmConfigBase):
    """NOAA/CIMSS alarm.

    ``max_distance`` is getattr-defaulted (25) in run_alarm, so it is optional.
    The ``elevated_volcano_*`` trio is read unguarded whenever an alert is
    sent, so those are required. ``thermal_alert_dist`` is defaulted but
    ``thermal_alerts_mm`` is read bare on the thermal path.
    """

    elevated_volcano_dist: Number
    elevated_volcano_list: list[str]
    elevated_volcano_mm: str
    max_distance: Union[Number, None] = None
    thermal_alert_dist: Union[Number, None] = None
    thermal_alerts_mm: Union[str, None] = None
    map_xdist: Union[Number, None] = None
    map_ydist: Union[Number, None] = None


class PilotReportConfig(AlarmConfigBase):
    """Pilot report (PIREP) alarm.

    ``non_urgent`` ships in the example config but is not read by the code
    (urgency comes from the PIREP record); declared so real files validate.
    """

    max_distance: Number
    duration: NumberOrExpr
    non_urgent: Union[bool, None] = None  # present in example, unused by code
    map_xdist: Union[Number, None] = None
    map_ydist: Union[Number, None] = None


class SO2Config(AlarmConfigBase):
    """SO2 alarm."""

    max_distance: Number


class VAAConfig(AlarmConfigBase):
    """VAA / SIGMET alarm."""

    duration: NumberOrExpr


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Maps the ``alarm_type`` discriminator to its validation model. Keys match
#: the alarm module/directory names (e.g. ``Pilot_Report``, not ``PIREP``).
SCHEMAS: dict[str, type[AlarmConfigBase]] = {
    "RSAM": RSAMConfig,
    "Tremor": TremorConfig,
    "Infrasound": InfrasoundConfig,
    "Lightning": LightningConfig,
    "Magnitude": MagnitudeConfig,
    "Swarm": SwarmConfig,
    "NOAA_CIMSS": NOAACIMSSConfig,
    "Pilot_Report": PilotReportConfig,
    "SO2": SO2Config,
    "VAA": VAAConfig,
}

#: YAML files that live alongside alarm configs but are not themselves alarm
#: configs, so :func:`validate_config_dir` skips them. This is an explicit
#: allowlist: every other ``*.yml`` is validated, so a missing or misspelled
#: ``alarm_type`` fails rather than being silently ignored.
NON_ALARM_FILES: frozenset[str] = frozenset({"distribution.yml", "phonebook.yml"})


class ConfigValidationError(Exception):
    """Raised when a config file fails schema validation.

    The message is formatted for direct display in CLI/CI output.
    """


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    """Render a Pydantic ValidationError as a readable, path-prefixed block."""
    lines = [f"{path}: {exc.error_count()} validation error(s):"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def validate_config(path: Union[str, Path]) -> AlarmConfigBase:
    """Validate a single alarm config YAML file against its schema.

    The file's ``alarm_type`` selects the model from :data:`SCHEMAS`.

    Parameters
    ----------
    path : str or Path
        Path to the ``.yml`` config file.

    Returns
    -------
    AlarmConfigBase
        The validated, parsed config model.

    Raises
    ------
    ConfigValidationError
        If the file cannot be read/parsed, is not a mapping, has an unknown or
        missing ``alarm_type``, or fails schema validation.
    """
    path = Path(path)

    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigValidationError(f"{path}: cannot read file: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigValidationError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigValidationError(
            f"{path}: config root must be a YAML mapping, got "
            f"{type(data).__name__}"
        )

    alarm_type = data.get("alarm_type")
    if alarm_type is None:
        raise ConfigValidationError(f"{path}: missing required field 'alarm_type'")

    schema = SCHEMAS.get(alarm_type)
    if schema is None:
        known = ", ".join(sorted(SCHEMAS))
        raise ConfigValidationError(
            f"{path}: unknown alarm_type '{alarm_type}'. Known types: {known}"
        )

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(_format_validation_error(path, exc)) from exc


def validate_config_dir(directory: Union[str, Path]) -> dict[Path, AlarmConfigBase]:
    """Validate every alarm ``*.yml`` config in a directory.

    Every ``*.yml`` file is treated as an alarm config and validated, except
    the known non-alarm support files named in :data:`NON_ALARM_FILES`
    (``distribution.yml``, ``phonebook.yml``). This is deliberately an
    allowlist, not an ``alarm_type``-presence check: a file whose discriminator
    is missing or misspelled (``alarm_typ: RSAM``) must fail loudly rather than
    be silently skipped. All validation errors are collected and reported
    together rather than failing on the first one.

    Parameters
    ----------
    directory : str or Path
        Directory containing alarm config files.

    Returns
    -------
    dict[Path, AlarmConfigBase]
        Mapping of each validated file to its parsed config model.

    Raises
    ------
    ConfigValidationError
        If the directory does not exist, or one or more configs fail
        validation (all failures are aggregated into the message).
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise ConfigValidationError(f"Config directory not found: {directory}")

    results: dict[Path, AlarmConfigBase] = {}
    errors: list[str] = []

    for yml in sorted(directory.glob("*.yml")):
        if yml.name in NON_ALARM_FILES:
            continue

        try:
            results[yml] = validate_config(yml)
        except ConfigValidationError as exc:
            errors.append(str(exc))

    if errors:
        raise ConfigValidationError("\n".join(errors))

    return results
