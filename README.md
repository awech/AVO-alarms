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
pip install .            # core dependencies
pip install .[avo]       # include AVO-specific extras (mattermost, enveloc, etc.)
```

## Running it
Copy `.env_example` to `.env` and fill in the relevant system parameters.

Usage:
```
run-alarm <config_name> [-t DATETIME] [--test] [--force] [--mm/--no-mm] [--icinga/--no-icinga]
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

## Configuration

### Rate limiting
Alarm rate-limiting is opt-in. Add both `alert_memory` and `max_alerts` to a config file to enable it:
```yaml
alert_memory: 3600  # lookback window (seconds)
max_alerts: 3       # max alerts within that window
```
If either key is absent, the alarm sends without any rate limit.

### Defaults
For RSAM, Infrasound, and Tremor configs, the following defaults are applied when not explicitly set:
| Parameter | RSAM / Tremor | Infrasound |
|-----------|---------------|------------|
| `taper`   | 5 s           | 5 s        |
| `latency` | 10 s          | 10 s       |
| `duration`| 300 s         | 180 s      |
| `vmin`    | —             | 0.28 km/s  |
| `vmax`    | —             | 0.45 km/s  |

### Arithmetic in config values
The `value` and `duration` keys support simple inline math so you can express intent clearly:
```yaml
value: 280 * 2.5       # evaluates to 700
duration: 3600 * 24 * 3  # evaluates to 259200
```
Only digits, decimal points, parentheses, and `+ - * /` are allowed.

## Notifications
Edit `config/distribution.yml` to define which recipients receive each alarm. By default, alerts go to the "All Alarms" list unless overridden by an alarm-specific entry (the header must match the `alarm_name` in the corresponding config file).

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
