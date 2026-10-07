# Alarm Configuration

## RSAM example
Below is an example configuration file for a single RSAM alarm. 

```yaml
alarm_type: RSAM                  # designates which alarm module will be imported and executed
alarm_name: Semisopochnoi RSAM    # alarm name sent to icinga and in message alerts

# Stations list
rsam_stations:
  - nslc: AV.CEAP..BHZ
    value: 650
  - nslc: AV.CERA..BHZ
    value: 750
  - nslc: AV.CETU..BHZ
    value: 650
  - nslc: AV.CESW..BHZ
    value: 900

# Arrestor station
arrestor:
  nslc: AV.AMKA..BHZ
  value: 350

# Processing parameters
f1: 1.0                # minimum frequency for bandpass filter
f2: 5.0                # maximum frequency for bandpass filter
min_sta: 3             # minimum number of stations for detection
# duration: 300        # Optional. Total window duration. Default: 300 s
# taper: 5             # Optional. Pre-filter taper. Default: 5 s
# latency: 10          # Optional. Delay when run from cron for data latency. Default: 10 s

# Alerting parameters
alert_memory: 3600     # lookback window (seconds)
max_alerts: 3          # max alerts within that window

# Plotting parameters
# plot_duration: 3600  # Optional. Window length for spectrogram plot. Default 3600 s
infrasound:            # Optional. List of infrasound channels to plot
  - AV.CERB..BDF
  - AV.CESW..BDF

# Optional volcano name used for calculating reduced displacement
# Name and lat/lon must be in target list file set as environment variable
# and `rsam_stations` metadata must be available in `STATION_XML`
volcano_name: Semisopochnoi
```

See more example files in `config/` to view available parameters for other alarm modules.

## Default Parameters

### Seismo-acoustic waveform defaults (RSAM, Infrasound, Tremor)

The following default parameters are applied to the various alarms. 
These can be overridden by the parameter key in the alarm config `.yml` file, or by the listed environment variable.
See comments in example files in `config/` for descriptions of individual parameters.

| Parameter        | RSAM     | Infrasound | Tremor   | Env variable (optional)  |
|------------------|----------|------------|----------|--------------------------|
| `taper`          | `5` s    | `5` s      | `5` s    | —                        |
| `latency`        | `10` s   | `10` s     | `10` s   | —                        |
| `duration`       | `300` s  | –          | —        | `RSAM_DURATION`          |
| `duration`       | —        | `90` s     | —        | `INFRASOUND_DURATION`    |
| `plot_duration`  | `3600` s | –          | `3600` s | `SPEC_PLOT_DURATION`     |
| `lookback_window`| —        | —          | `60` s   | `TREMOR_LOOKBACK_WINDOW` |
| `window_length`  | —        | —          | `300` s  | `TREMOR_WINDOW_LENGTH`   |

### Infrasound-specific defaults

The following default parameters are applied to the infrasound alarms.
See comments in example files in `config/` for descriptions of individual parameters.

| Parameter          | Default     | Env variable (optional)    |
|--------------------|------------ |----------------------------|
| `min_channels`     | `3`         | `INFRASOUND_MIN_CHANNELS`  |
| `lts_window_length`| `30` s      | `LTS_WINDOW_LENGTH`        |
| `lts_overlap`      | `15` s      | `LTS_OVERLAP`              |
| `lts_alpha`        | `0.5`       | `LTS_ALPHA`                |
| `lts_n_samples`    | `100`       | `LTS_N_SAMPLES`            |
| `max_gap_fraction` | `0.5`       | `MAX_GAP_FRACTION`         |
| `vmin`             | `0.28` km/s | `INFRASOUND_VMIN`          |
| `vmax`             | `0.45` km/s | `INFRASOUND_VMAX`          |
| `cmin`             | `0.6`       | `INFRASOUND_CMIN`          |
| `plot_duration`    | `3600` s    | `INFRASOUND_PLOT_DURATION` |

The `vmin`, `vmax`, `cmin`, and `plot_duration` values may be set per target, at the config top level, or via the environment variable (in that order of precedence) before falling back to the hard-coded default.

## Arithmetic in config values

Keys containing the string `value` and `duration` support simple inline math so you can express intent clearly:

```yaml
value: 280 * 2           # evaluates to 560 (e.g., doubling an existing RSAM value)
duration: 3600 * 24 * 3  # evaluates to 259200 (e.g., 3 days duration in seconds)
```

Only digits, decimal points, parentheses, and `+ - * /` are allowed.

## Rate limiting

Alarm rate-limiting is opt-in, and useful to silence alarms after sending more than `N` alerts in `T` time.
Add both `alert_memory` and `max_alerts` to a config file to enable it:

```yaml
alert_memory: 3600  # lookback window (seconds)
max_alerts: 3       # max alerts within that window
```