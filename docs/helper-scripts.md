# Helper Scripts

These console scripts are installed alongside `run-alarm` (see the `[project.scripts]` table in `pyproject.toml`).

!!! note "Common argument"
    Every script below accepts `--env-file PATH`, which points at a `.env` file to load. If omitted, the directory tree is searched upward for one. It is not repeated in each table.

## `run-alarm`

Run a single alarm. Loads the named config, acquires a single-instance lock, and dispatches to the matching alarm module.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `config` | positional | required | Name of the config file in `CONFIGS_DIR`, with or without the `.yml`/`.yaml` extension (e.g. `RSAM` or `RSAM.yml`). |
| `-t`, `--time` | string | current UTC | UTC timestamp `YYYYMMDDHHMM`. If omitted, uses the current UTC time rounded down to the minute. |
| `--test` | flag | off | Run in test mode (test tables/channels, TEST watermark). |
| `--force` | flag | off | Force a trigger. Implies `--test`. |
| `--earthscope` | flag | off | Use the Earthscope FDSN client for waveform downloads instead of Winston. |
| `--mm` | flag | off | Post to Mattermost. |
| `--icinga` | flag | off | Send a heartbeat to Icinga. |

```bash
run-alarm Pavlof_RSAM
run-alarm --test -t 201701020205 Pavlof_RSAM
```

## `generic-alarm`

Set a named alarm service to an empty `OK` state in Icinga. Useful for alarm services that have no detection logic of their own but still need a periodic heartbeat.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `alarm` | positional | required | Alarm name. Use `_` in place of spaces. |

```bash
generic-alarm Some_Service_Name
```

## `update-metadata`

Download and refresh station metadata (`STATION_XML` file). Typically run on a daily cron. It scrapes NSLC info from all RSAM, Infrasound, and Tremor config files and pulls metadata from Earthscope. Requires environment variable `CONFIG_DIR` defined.

This script takes no arguments beyond the common `--env-file`.

```bash
update-metadata
```

## `list-alerts`

Query the alarm history database. Filter by alarm name, volcano, and/or a UTC time range (explicit start/end, or a duration before present).

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `-a`, `--alarm` | string | — | Alarm name to filter by. Use `_` in place of spaces. |
| `-v`, `--volcano` | string | — | Volcano name to filter by. Use `_` in place of spaces. |
| `-t`, `--test` | flag | off | Query the `test_sent_events` table instead of the production table. |
| `-s`, `--starttime` | string | — | Window start in UTC: `YYYYMMDDHHMM`. |
| `-e`, `--endtime` | string | — | Window end in UTC: `YYYYMMDDHHMM`. |
| `-dt`, `--duration` | string | — | Window length relative to a start or end time: a number plus unit `h` (hours), `d` (days), or `m` (minutes), e.g. `3h`. See the rules below for direction. |

Time-window rules:

- Start must be before end.
- A duration cannot be combined with both a start and an end.
- With `-s` (start) and `-dt`, the window extends **forward** from the start (`end = start + duration`).
- With `-e` (end) and `-dt`, the window extends **backward** from the end (`start = end - duration`).
- With `-dt` alone, the window is measured **backward from the present** (`now - duration` to `now`).

```bash
list-alerts -a Pavlof_RSAM
list-alerts -v Pavlof -dt 3d
list-alerts -s 202501010000 -e 202501020000
```

## `update-html`

Regenerate the notification distribution HTML matrix from `distribution.yml`. Outputs to the path defined by `WWW_FILE` in `.env`.

This script takes no arguments beyond the common `--env-file`.

```bash
update-html
```

## `email-test`

Send a test email (with the bundled `oops.jpg` attachment) to the "Test" distribution list to verify that the email relay is working.

This script takes no arguments beyond the common `--env-file`.

```bash
email-test
```

## `get-rsam-levels`

Compute the RSAM count levels for stations for a given reduced displacement (DR) value. Provide stations either from an alarm config or explicitly with `--nslc` + `--volcano`.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `DR` | positional (float) | required | Target reduced displacement in cm². |
| `--config` | string | — | Name of an alarm config file supplying the volcano name and station list. Mutually exclusive with `--nslc`/`--volcano`. |
| `--nslc` | string(s) | — | One or more NSLC strings (e.g. `AV.PN7A..BHZ`), space-separated. Requires `--volcano`. |
| `--volcano` | string | — | Volcano name. Used with `--nslc`, or to override the config volcano. Must be in the `VOLCANO_LIST` environment file. |
| `--base` | int | `25` | Rounding base for the output RSAM levels. |

You must provide either `--config` or `--nslc` (with `--volcano`).

```bash
# use a config file (with `volcano` key set)
get-rsam-levels 2.0 --config Pavlof_RSAM

# use `--nslc` to manually set a list of stations (separated by single space)
# use `--volcano` to manually set volcano (must be in `VOLCANO_LIST` environment variable file)
get-rsam-levels 5.0 --nslc AV.PN7A..BHZ AV.PS4A..BHZ AV.BLDW..BHZ --volcano Pavlof

# override the default rounding base
get-rsam-levels 2.0 --config Pavlof_RSAM --base 50
```
