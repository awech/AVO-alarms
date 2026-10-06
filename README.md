# volc-alarms
Python codes used for geophysical alarms at AVO. Currently (2026-Jun-18) running on Python 3.13.13

## Python Dependencies
Core:
- obspy
- pandas
- pyyaml
- jinja2
- cartopy
- cmcrameri
- matplotlib
- numba
- numpy
- python-dotenv
- utm
- scikit-learn
- requests
- scipy
- tabulate

Optional (AVO-specific, install with `pip install .[avo]`):
- beautifulsoup4
- enveloc
- pillow
- mattermostdriver
- openpyxl

## Install
```bash
pip install -e .            # core dependencies
pip install -e .[avo]       # include AVO-specific extras (mattermost, enveloc, etc.)
```

## Running it
Copy `.env_example` to `.env` and fill in the relevant system parameters.

Usage:
```
run-alarm <config_name> [-t/--time DATETIME] [--test] [--force] [--earthscope] [--mm] [--icinga] [--env-file]
```

Examples:
```bash
# Run with current time
run-alarm Pavlof_RSAM

# Run with a specific time
run-alarm Pavlof_RSAM -t 201701020205

# Test mode (no real notifications)
run-alarm Pavlof_RSAM --test --force

# Cron entry (minutely)
* * * * * cd /path/to/dev-alarms && run-alarm CLCO_Infrasound > /dev/null 2>&1
```

If no `-t` time is given, the current UTC minute is used.

## System Configuration

`utils/setup_utils.py` applies the following defaults when values are not explicitly set via `.env` or shell exports

### Directory paths
Inferred from the installed package location (project root).

| Parameter      | Environment variable | Default                        |
|----------------|----------------------|--------------------------------|
| Configs dir    | `CONFIGS_DIR`        | `<project_root>/config`        |
| Logs dir       | `LOGS_DIR`           | `<project_root>/logs`          |
| Lock dir       | `LOCK_DIR`           | `<project_root>/locks`         |
| Temp figure dir| `TMP_FIGURE_DIR`     | `<project_root>/tmp_files`     |

### File paths

| Parameter        | Environment variable | Default                                               |
|------------------|----------------------|-------------------------------------------------------|
| Database file    | `DB_FILE`            | `<tmp_files>/alarms_sent.db`                          |
| Distribution file| `DISTRIBUTION_FILE`  | `<CONFIGS_DIR>/distribution.yml`                      |
| Phonebook file   | `PHONEBOOK_FILE`     | `<project_root>/config/phonebook.yml`                 |
| Volcano list     | `VOLCANO_LIST`       | `<project_root>/src/volc_alarms/data/volcano_list.csv`|
| Station metadata | `STATION_XML`        | `<tmp_files>/stations.xml`                            |
| Distribution HTML| `WWW_FILE`           | `<tmp_files>/index.html`                              |

### Waveserver / data access

| Parameter      | Environment variable | Default       |
|----------------|----------------------|---------------|
| Winston host   | `WINSTON_HOST`       | `127.0.0.1`   |
| Winston port   | `WINSTON_PORT`       | `16022`       |
| Winston timeout| `TIMEOUT`            | `20` s        |
| FDSN timeout   | `FDSN_TIMEOUT`       | `60` s        |

### External data URLs

| Parameter | Environment variable | Default                                                            |
|-----------|----------------------|-------------------------------------------------------------------|
| PIREP     | `PIREP_URL`          | `https://mesonet.agron.iastate.edu/cgi-bin/request/gis/pireps.py` |
| VAA       | `VAA_URL`            | `https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil=VAA` |
| SACS      | `SACS_URL`           | `http://sacs.aeronomie.be/lastNOTIFICATION.php`                   |

### Email (SMTP)

| Parameter     | Environment variable | Default                             |
|---------------|----------------------|-------------------------------------|
| SMTP security | `SMTP_SECURITY`      | `ssl` (implicit TLS; or `starttls`) |

### Logging & timezone

| Parameter             | Environment variable | Default                  |
|-----------------------|----------------------|--------------------------|
| Timezone              | `TIMEZONE`           | system TZ (fallback UTC) |
| Log rotation interval | `LOG_HOUR_INTERVAL`  | `12` h                   |
| Log retention         | `LOG_DAYS_KEEP`      | `7` days                 |

## Alarm configurations
The following default parameters are applied to the various alarm. These can be overridden by the parameter key in the alarm config .yml file, by the listed environment variable.

#### Seismo-acoustic waveform defaults (RSAM, Infrasound, Tremor)
Applied per alarm type when the config does not set them.

| Parameter      | Environment variable      | RSAM  | Infrasound | Tremor |
|----------------|---------------------------|-------|------------|--------|
| `taper`        | —                         | 5 s   | 5 s        | 5 s    |
| `latency`      | —                         | 10 s  | 10 s       | 10 s   |
| `duration`     | `RSAM_DURATION` / `INFRASOUND_DURATION` | 300 s | 90 s | —      |
| `plot_duration`| `SPEC_PLOT_DURATION` (RSAM/Tremor) / `INFRASOUND_PLOT_DURATION` | 3600 s | 3600 s | 3600 s |
| `lookback_window`| `TREMOR_LOOKBACK_WINDOW`| —     | —          | 60 s   |
| `window_length`| `TREMOR_WINDOW_LENGTH`    | —     | —          | 300 s  |

#### Infrasound-specific defaults

| Parameter          | Default     | Environment variable      |
|--------------------|------------ |---------------------------|
| `min_channels`     | `3`         | `INFRASOUND_MIN_CHANNELS` |
| `lts_window_length`| `30` s      | `LTS_WINDOW_LENGTH`       |
| `lts_overlap`      | `15` s      | `LTS_OVERLAP`             |
| `lts_alpha`        | `0.5`       | `LTS_ALPHA`               |
| `lts_n_samples`    | `100`       | `LTS_N_SAMPLES`           |
| `max_gap_fraction` | `0.5`       | `MAX_GAP_FRACTION`        |
| `vmin`             | `0.28` km/s | `INFRASOUND_VMIN`         |
| `vmax`             | `0.45` km/s | `INFRASOUND_VMAX`         |
| `cmin`             | `0.6`       | `INFRASOUND_CMIN`         |

The `vmin`, `vmax`, `cmin`, and `plot_duration` values may be set per target, at the config top level, or via the environment variable (in that order of precedence) before falling back to the hard-coded default.

#### Arithmetic in config values
The `value` and `duration` keys support simple inline math so you can express intent clearly:
```yaml
value: 280 * 2.5       # evaluates to 700
duration: 3600 * 24 * 3  # evaluates to 259200
```
Only digits, decimal points, parentheses, and `+ - * /` are allowed.

#### Rate limiting
Alarm rate-limiting is opt-in. Add both `alert_memory` and `max_alerts` to a config file to enable it:
```yaml
alert_memory: 3600  # lookback window (seconds)
max_alerts: 3       # max alerts within that window
```
If either key is absent, the alarm sends without any rate limit.


## Notifications
Edit `config/distribution.yml` (or the files specified by the `DISTRIBUTION_FILE` environment variable) to define which recipients receive each alarm.
By default, alerts go to the "All Alarms" list unless overridden by an alarm-specific entry (the header must match the `alarm_name` in the corresponding config file).

Recipients are defined in `config/phonebook.yml` (or the file specified by the `PHONEBOOK_FILE` environment variable).


## Helper Scripts

### `list-alerts`
Query the alarm history database. Filter by alarm name, volcano, time range, or duration.
```bash
list-alerts -a Pavlof_RSAM
list-alerts -v Pavlof -dt 3d
list-alerts -s 202501010000 -e 202501020000
```
Use `--test` to query the test table instead.

### `update-metadata`
Download and refresh station metadata (StationXML). Typically run on a daily cron. It scrapes NSLC info from all RSAM, Infrasound and Tremor config files and pulls metadata from Earthscope.
```bash
update-metadata
```

### `update-html`
Regenerate the notification distribution HTML matrix from `distribution.yml`. Outputs to the path defined by `WWW_FILE` in `.env`.
```bash
update-html
```

### `email-test`
Send a test email to the "Error" distribution list to verify that the email relay is working.
```bash
email-test
```

### `get-rsam-levels`
Compute the RSAM count levels for stations for a given reduced displacement value
```bash
# use a config file (with volcano key set)
get-rsam-levels 2.0 --config Pavlof_RSAM

# use --nslc to manually set a list of stations (separated by single space) 
# use --volcano to manually set volcano (must be in VOLCANO_LIST environment variable file)
get-rsam-levels 5.0 --nslc AV.PN7A..BHZ AV.PS4A..BHZ AV.BLDW..BHZ --volcano Pavlof
```

## Icinga Monitoring

Icinga integration is **opt-in**. Each alarm run can report a heartbeat to an [Icinga2](https://icinga.com/docs/icinga-2/latest/doc/01-about/) monitoring server so you can tell the difference between "the alarm ran and found nothing" and "the alarm stopped running", or "the alarm failed silently". 

### How it works

When `run-alarm` is passed the `--icinga` flag, the alarm sends its final state to an Icinga2 service as a passive check result via the Icinga2 REST API (`actions/process-check-result`). The state maps to standard monitoring exit codes:

| State      | Exit code | Meaning                                              |
|------------|-----------|------------------------------------------------------|
| `OK`       | 0         | Alarm ran normally (detection or no detection)       |
| `WARNING`  | 1         | Degraded run — e.g. data-quality/latency issue, or the config kill switch is active |
| `CRITICAL` | 2         | Alarm triggered                     |
| `UNKNOWN`  | 3         | Hung or failed silently and stopped sending heartbeats |

### Environment variables

Add the following to your `.env` (see `.env_example`). All four are required when running with `--icinga`:

| Variable          | Description                                                        |
|-------------------|--------------------------------------------------------------------|
| `ICINGA_URL`      | Full URL to the Icinga2 `process-check-result` API endpoint        |
| `ICINGA_HOST_NAME`| Icinga host object the alarm services are attached to              |
| `ICINGA_USERNAME` | Icinga2 API user with permission to submit check results           |
| `ICINGA_PASSWORD` | Password for that API user                                         |


### Service naming

By default the alarm's `alarm_name` (from the alarm's config `.yml`) is used as the Icinga service name. To point an alarm at a differently named Icinga service, set `icinga_service_name` in the config:

```yaml
icinga_service_name: Pavlof RSAM heartbeat
```

### Heartbeats for alarms without detection logic

Some services exist only to as retainers to quickly spin up a future alarm and monitor it. Use the `generic-alarm` console script to push a plain `OK` heartbeat for a named service:

```bash
generic-alarm Pipeline_Heartbeat          # '_' is converted to spaces -> "Pipeline Heartbeat"
generic-alarm Pipeline_Heartbeat --env-file /path/to/.env
```

### Enabling it on a cron

Add `--icinga` to the alarm invocation so the heartbeat is actually sent (it is off unless the flag is present):

```bash
* * * * * cd /path/to/dev-alarms && FROMCRON=yep run-alarm Pavlof_RSAM --icinga > /dev/null 2>&1
```
