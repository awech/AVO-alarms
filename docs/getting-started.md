# Getting Started

## Overview


`volc-alarms` is run using a combination of environment variables and parameters set by individual alarm configure (.yml) files.
At its core, it is run via command line by point the CLI script `run-alarm` at a config file name.

```bash
run-alarm <config_name> [-t/--time DATETIME] [--test] [--force] [--earthscope] [--mm] [--icinga] [--env-file]
```

Before running things, it is important to set up the environment to point to appropriate directories, waveservers, etc.
It is recommended that you copy the `.env_example` file to `.env` and fill in the relevant system parameters.
`utils/setup_utils.py` tries to set a number of defaults, including some input and out directories, but these paths are relative to the project root and manually defining directories as environment variables is highly recomended.

### Directory stucture
A typical layout keeps the alarm working directories alongside the cloned repository:

```text
alarms/
├── volc-alarms/    # the cloned repository / installed package
├── configs/        # alarm config .yml files         (CONFIGS_DIR)
├── alarm_locks/    # .lock files for running alarms  (LOCK_DIR)
├── logs/           # .log output                     (LOGS_DIR)
├── data_files/     # input data (STATION_XML, DB_FILE, VOLCANO_LIST, PHONEBOOK_FILE, etc.)
└── tmp_figures/    # temporary .png figures for alerts (TMP_FIGURE_DIR)

```

### Key environment variables
 The most important environment variables are:

- `CONFIGS_DIR`: path to individual alarm config files reside
- `LOGS_DIR` - path to write `.log` output
- `LOCK_DIR` - path to write `.lock` files
- `TMP_FIGURE_DIR` - path for .png file output so temporarily save while attaching to an alert
- `DB_FILE` - `<name>.db` file for the sqlite database to record sent alerts
- `STATION_XML` - station .xml file with metadata supporting channels in various alarm configs
- `DISTRIBUTION_FILE` - .yml file defining alert distribution. See `volc-alarms/config/distribution.yml` example
- `VOLCANO_LIST` - .csv (.xlsx) file with Name,Latitude,Longitude headers. See `volc-alarms/src/volc_alarms/data/volcano_list.csv` example
- `PHONEBOOK_FILE` - .yml file linking distribution list to email or sms. Not to be inlcuded in public-facing repo. See `volc-alarms/config/phonebook.yml` example
- `SMTP_IP` - ip_address for sending email via smtp
- `SMTP_PORT` - port # for sending email via smtp
- `WINSTON_HOST`: winston waveserver IP address 
- `WINSTON_PORT`: winston waveserver port number


## Defaults

`utils/setup_utils.py` applies the following defaults when values are not explicitly set via `.env` or shell exports.

### Directory paths

Inferred from the installed package location (project root).

| Parameter       | Environment variable | Default                        |
|-----------------|----------------------|--------------------------------|
| Configs dir     | `CONFIGS_DIR`        | `<project_root>/config`        |
| Logs dir        | `LOGS_DIR`           | `<project_root>/logs`          |
| Lock dir        | `LOCK_DIR`           | `<project_root>/locks`         |
| Temp figure dir | `TMP_FIGURE_DIR`     | `<project_root>/tmp_files`     |

### File paths

| Parameter         | Environment variable | Default                                               |
|-------------------|----------------------|-------------------------------------------------------|
| Database file     | `DB_FILE`            | `<tmp_files>/alarms_sent.db`                          |
| Distribution file | `DISTRIBUTION_FILE`  | `<CONFIGS_DIR>/distribution.yml`                      |
| Phonebook file    | `PHONEBOOK_FILE`     | `<project_root>/config/phonebook.yml`                 |
| Volcano list      | `VOLCANO_LIST`       | `<project_root>/src/volc_alarms/data/volcano_list.csv`|
| Station metadata  | `STATION_XML`        | `<tmp_files>/stations.xml`                            |
| Distribution HTML | `WWW_FILE`           | `<tmp_files>/index.html`                              |

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

| Parameter       | Environment variable | Default                             |
|-----------------|----------------------|-------------------------------------|
| SMTP security   | `SMTP_SECURITY`      | `ssl` (implicit TLS; or `starttls`) |


### Logging & timezone

| Parameter             | Environment variable | Default                  |
|-----------------------|----------------------|--------------------------|
| Timezone              | `TIMEZONE`           | system TZ (fallback UTC) |
| Log rotation interval | `LOG_HOUR_INTERVAL`  | `12` h                   |
| Log retention         | `LOG_DAYS_KEEP`      | `7` days                 |


## Alarm Workflow

Every alarm is a single, self-contained run of `run-alarm <config_name>`. The `run-alarm` script handles the shared setup, locking, and dispatch, then hands off to the alarm module named by the config's `alarm_type`. A typical cron fires one invocation every 1 to 5 minutes per config.

### 1. Setup and dispatch

`run-alarm` (`scripts/run_alarm.py`) does the common bookkeeping before any alarm logic runs:

1. **Parse arguments** and resolve the processing time `T0` — the current UTC minute, or the `-t YYYYMMDDHHMM` timestamp if given.
2. **Load the environment** by searching up the directory tree for a `.env`, or from `--env-file`
3. **Configure logging** — rotating file logs under cron (if env var `FROMCRON=yep`), otherwise console output.
4. **Acquire a lock** (`LockFile`) so only one instance of a given config runs at a time. If the config is already locked, the run exits immediately.
5. **Load the config** and honor its kill switch: if `kill: true`, send a `WARNING` Icinga heartbeat and exit without running (if `--icinga` is set).
6. **Dispatch** by dynamically importing `volc_alarms.alarms.<alarm_type>` and calling its `run_alarm`, forwarding the `--test`, `--mm`, `--icinga`, and `--force` flags.
7. On any **uncaught error**, email a traceback to the `Error` recipients; the lock is always released and the elapsed time logged.

### 2. Detect and classify

Each alarm module's `run_alarm` implements the type-specific logic (see [Alarm Modules](alarm-modules.md)), but the shape is consistent:

1. **Apply cron latency/backup** (`apply_cron_latency_backup`): under cron, either sleep for short-latency data or back `T0` up to the previous minute mark.
2. **Acquire data** for the processing window — waveforms from Winston/Earthscope, or records from an FDSN event service or an external API/feed.
3. **Process and evaluate** the data against the config's thresholds and filters.
4. **Classify the result** into a monitoring state:
    - `CRITICAL` — a detection; proceed to the send sequence below.
    - `WARNING` — degraded or elevated (e.g. missing data, arrested, elevated-but-not-triggered).
    - `OK` — normal.

Non-critical states report an Icinga heartbeat (when `--icinga` is set) and the run ends there.

### 3. Send sequence (on a detection)

When a module classifies a run as `CRITICAL`, it calls the shared `run_send_sequence` (`utils/alarm_flow.py`), which runs these eight steps in order:

1. **Rate-limit check** (`alarming.can_send`) — if the config opts into rate limiting (`alert_memory` + `max_alerts`) and the limit is hit, the alert is skipped, an Icinga heartbeat is sent, and the sequence returns early. See [Alarm Configuration → Rate limiting](alarm-configuration.md#rate-limiting).
2. **Build the figure** and output to `TMP_FIGURE_DIR`. A figure failure is logged but does not abort the alert.
3. **Create the message** — the module produces the alert `(subject, message)`. If this is the last alert before rate-limit suppression, a notice is appended.
4. **Post to Mattermost** (guarded) when `--mm` is set, with optional per-volcano channel routing. See [Alerting → Mattermost](alerting.md#mattermost).
5. **Send email/SMS** to the config's distribution list (resolved via `DISTRIBUTION_FILE` and `PHONEBOOK_FILE`).
6. **Record the send** to the SQLite database (`DB_FILE`) so rate limiting and de-duplication work on later runs.
7. **Clean up** (remove) the temporary figure file.
8. **Send the Icinga heartbeat** reporting the final state.

!!! note "Flag defaults"
    Mattermost (`--mm`) and Icinga (`--icinga`) are **off** unless their flags are passed. Running without them exercises the full detection logic while suppressing outbound chat posts and heartbeats — handy alongside `--test` (which uses test tables/channels and watermarks figures) and `--force` (which forces a trigger and implies `--test`).
