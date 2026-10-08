# System Configuration

## Overview

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
- `DISTRIBUTION_FILE` - .yml file defining alert distribution. See `config/distribution.yml` example
- `VOLCANO_LIST` - .csv (.xlsx) file with Name,Latitude,Longitude headers. See `src/volc_alarms/data/volcano_list.csv` example
- `PHONEBOOK_FILE` - .yml file linking distribution list to email or sms. Not to be inlcuded in public-facing repo. See `config/phonebook.yml` example
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
| Distribution file | `DISTRIBUTION_FILE`  | `<project_root>/config/distribution.yml`              |
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
