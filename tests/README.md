# Tests

## Directory structure

```
tests/
├── README.md                   # This file
├── __init__.py                 # Makes tests/ importable for cross-file imports
├── alarms/                     # Regression tests for alarm behavior
│   ├── conftest.py             # Test setup and shared fixtures
│   ├── fakes.py                # Fake services (replaces network, DB, email, etc.)
│   ├── scenarios.py            # Test inputs + alarm invocations for each alarm type
│   ├── snapshot_utils.py       # Captures alarm outputs and saves/loads JSON snapshots
│   ├── baselines/              # Saved "known-good" JSON outputs (auto-generated)
│   ├── test_regression.py      # Main tests: run alarms and compare to saved snapshots
│   └── test_setup_verification.py  # Verifies the test fakes themselves work correctly
└── make_map.py                 # Standalone script for generating map plotting examples
```

## How the regression tests work

The goal is to catch unintended changes to alarm behavior during code changes.

1. **Fakes** (`fakes.py`) replace every external service — network downloads,
   database, email, Mattermost, Icinga — with fake versions that record what
   was called but don't actually do anything.

2. **Scenarios** (`scenarios.py`) set up fake data and run each alarm's
   `run_alarm()` at a fixed time. Each scenario represents a specific situation
   (e.g., "RSAM with high signal → CRITICAL detection").

3. **Snapshots** (`snapshot_utils.py` + `baselines/*.json`) capture what the
   alarm *did* — what messages it sent, what Icinga state it reported, what it
   wrote to the DB — and save it as a JSON file.

4. **Tests** (`test_regression.py`) re-run the scenarios and check that the
   outputs still match the saved JSON snapshots exactly.


## What is and isn't being tested

### What the tests capture (for every alarm):

- **Icinga state** — the monitoring state reported (OK / WARNING / CRITICAL) and
  the status message text
- **Mattermost** — whether a post was made, and with what subject/body
- **Email** — whether an alert was sent, and with what subject/body
- **DB write** — whether `record_send` was called, and with what alarm_id,
  volcano, and event_id
- **File cleanup** — whether `os.remove` was called (figure deleted after sending)
- **Call order** — the sequence of all the above (e.g., did Icinga get called
  after Mattermost?)

### What is NOT tested:

- **Figure content** — matplotlib is completely bypassed; a placeholder file
  path is returned instead of generating a real plot
- **Detection algorithm correctness** — threshold math, signal processing, etc.
  are only exercised indirectly (the tests confirm the *outcome* doesn't change,
  not that the outcome is *correct*)
- **Message formatting** — captured in snapshots as a side effect, but there are
  no dedicated tests asserting specific formatting rules
- **External service behavior** — no integration tests against real Mattermost,
  Icinga, SMTP, or data APIs

### Current scenario coverage by alarm:

| Alarm | Scenarios | What's exercised |
|-------|-----------|------------------|
| RSAM | `representative`, `critical` | Full pipeline: detection → Mattermost → email → DB write → cleanup |
| Lightning | `representative`, `critical` | Full pipeline with crafted stroke data |
| Infrasound | `representative` only | Early WARNING ("not enough channels") |
| Tremor | `representative` only | Early WARNING ("data missing") |
| NOAA_CIMSS | `representative` only | Early WARNING ("API error") |
| Pilot_Report | `representative` only | OK ("no new reports") |
| SO2 | `representative` only | Early WARNING ("webpage error") |
| VAA | `representative` only | Early WARNING ("webpage error") |
| Magnitude | `representative` only | OK ("no new earthquakes") |
| Swarm | `representative` only | OK ("no new swarm activity") |

Most alarms only have a "nothing happened" scenario because triggering their
CRITICAL path requires complex fake data (scraped HTML pages, FDSN XML
responses, shapefiles, etc.) that hasn't been built yet.

### What's missing (opportunities for future tests):

- **CRITICAL scenarios** for remaining alarms (Infrasound, Tremor, NOAA_CIMSS,
  Pilot_Report, SO2, VAA, Magnitude, Swarm) — would require crafting realistic
  fake data for each alarm's download/detection pipeline
- **Unit tests for detection logic** — test individual functions like
  `RSAM_to_DR()`, `run_enveloc()`, or `check_volcano_mention()` in isolation
  with known inputs and expected outputs
- **Message formatting tests** — verify specific text patterns, volcano names,
  timestamps appear correctly in alert messages
- **Figure content tests** — verify plot elements (map extent, station markers,
  axis labels) are correct for given inputs
- **Configuration validation tests** — verify alarms fail gracefully with
  missing or malformed config values
- **Edge cases** — data gaps, timezone boundaries, network timeouts, empty
  responses, duplicate events


## Running tests

```bash
pytest tests/                       # Run everything
pytest tests/alarms/                # Run only alarm regression tests
pytest tests/alarms/ -k "RSAM"      # Run only RSAM scenarios
```

## Updating snapshots after intentional changes

When you deliberately change alarm behavior (e.g., modify detection thresholds
or message formatting), the regression tests will fail because the output no
longer matches the saved snapshot. To update:

```bash
REGEN_BASELINES=1 pytest tests/alarms/test_regression.py
```

This overwrites the saved JSON files with the new output. Always review the
diffs (`git diff`) before committing to make sure the changes are expected.
