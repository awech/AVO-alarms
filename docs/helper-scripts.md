# Helper Scripts

These console scripts are installed alongside `run-alarm` (see the `[project.scripts]` table in `pyproject.toml`).

## `update-metadata`

Download and refresh station metadata (`STATION_XML` file). Typically run on a daily cron. It scrapes NSLC info from all RSAM, Infrasound, and Tremor config files and pulls metadata from Earthscope.

```bash
update-metadata
```

## `list-alerts`

Query the alarm history database. Filter by alarm name, volcano, time range, or duration.

```bash
list-alerts -a Pavlof_RSAM
list-alerts -v Pavlof -dt 3d
list-alerts -s 202501010000 -e 202501020000
```

Use `--test` to query the test table instead.

## `update-html`

Regenerate the notification distribution HTML matrix from `distribution.yml`. Outputs to the path defined by `WWW_FILE` in `.env`.

```bash
update-html
```

## `email-test`

Send a test email to the "Error" distribution list to verify that the email relay is working.

```bash
email-test
```

## `get-rsam-levels`

Compute the RSAM count levels for stations for a given reduced displacement value.

```bash
# use a config file (with `volcano` key set)
get-rsam-levels 2.0 --config Pavlof_RSAM

# use `--nslc` to manually set a list of stations (separated by single space)
# use `--volcano` to manually set volcano (must be in `VOLCANO_LIST` environment variable file)
get-rsam-levels 5.0 --nslc AV.PN7A..BHZ AV.PS4A..BHZ AV.BLDW..BHZ --volcano Pavlof
```
