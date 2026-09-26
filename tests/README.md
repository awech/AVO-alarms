# Tests

This suite is organized so an unfamiliar reviewer can quickly see **what is
tested, where, and how**. It is split by *target* (which part of the package)
and then by *type* (unit vs integration).

## Two kinds of tests

| Type | Marker | What it does | How it mocks |
|------|--------|--------------|--------------|
| **Unit** | `@pytest.mark.unit` | Exercises a single function with crafted inputs and asserts its output/behavior. Fast and isolated. | Local mocking only — it mocks *just* the one external call the function under test makes (a download, `save_file`, etc.). Never touches the real network, database, email, or renders a real figure. |
| **Integration** | `@pytest.mark.integration` | Drives a whole alarm's `run_alarm()` end to end and compares its observable behavior (Icinga state, Mattermost/email sends, DB writes, file cleanup, call order) to a frozen JSON baseline. | The shared **fakes harness** (`tests/_harness/`) replaces *every* external service at once. |

Run a slice:

```bash
pytest -m unit           # fast, isolated function tests
pytest -m integration    # full run_alarm() regression against baselines
pytest                   # everything
```

## Directory layout

```
tests/
├── README.md                       # this file (conventions + coverage matrix)
├── __init__.py
├── conftest.py                     # shared env setup + fixtures (unit + integration)
├── _harness/                       # shared integration machinery (NOT tests)
│   ├── fakes.py                    # CallRecorder, FakeAlarmDB, AlarmDoubles, install()
│   ├── snapshot_utils.py           # capture behavior + save/load baseline JSON
│   ├── scenarios.py                # per-alarm run_alarm scenario drivers
│   └── baselines/                  # frozen known-good JSON snapshots
├── utils/                          # unit tests for volc_alarms.utils.*
│   ├── test_alarming.py
│   ├── test_messaging.py
│   ├── test_processing.py
│   ├── test_plotting.py
│   ├── test_setup_utils.py
│   ├── test_downloading.py
│   └── test_alarm_flow.py
├── alarms/                         # one folder per alarm
│   ├── test_harness_smoke.py       # verifies the fakes/doubles themselves
│   └── <Alarm>/
│       ├── test_detection.py       # unit: detection.py logic
│       ├── test_message.py         # unit: message.py formatting
│       ├── test_figure.py          # unit: figure.py logic (save_file mocked)
│       └── test_run_alarm.py       # integration: scenario -> snapshot -> baseline
├── scripts/                        # unit tests for volc_alarms.scripts.*
│   └── test_run_alarm_cli.py
└── fixtures/                       # shared static data + crafted sample inputs
    └── data/station.xml
```

## Naming and docstring conventions

- **Files:** `test_<module>.py` for utils; `test_detection.py` / `test_message.py`
  / `test_figure.py` for an alarm's units; `test_run_alarm.py` for an alarm's
  integration test.
- **Test functions:** `test_<function>_<behavior>`, e.g.
  `test_process_polygons_parses_two_ring_field`.
- **Docstrings:** the first line names the function under test and the behavior
  being asserted. No references to bug-tracker IDs or spec requirement numbers.

## Updating integration baselines

When you deliberately change alarm behavior, the integration tests will fail
because the captured behavior no longer matches the frozen JSON. Regenerate and
review the diff before committing:

```bash
REGEN_BASELINES=1 pytest -m integration
git diff tests/_harness/baselines
```

## Coverage matrix

> Filled in as the suite is built out (see the framework task list). Legend:
> ✅ covered · ⬜ planned · N/A intentionally not unit-tested (integration-only).

### utils

| Module | Unit test file | Status |
|--------|----------------|--------|
| `alarming` | `utils/test_alarming.py` | ⬜ |
| `messaging` | `utils/test_messaging.py` | ⬜ |
| `processing` | `utils/test_processing.py` | ⬜ |
| `plotting` | `utils/test_plotting.py` | ⬜ |
| `setup_utils` | `utils/test_setup_utils.py` | ⬜ |
| `downloading` | `utils/test_downloading.py` | ⬜ |
| `alarm_flow` | `utils/test_alarm_flow.py` | ⬜ |

### alarms

| Alarm | detection | message | figure | run_alarm (integration) |
|-------|-----------|---------|--------|-------------------------|
| Infrasound | ⬜ | ⬜ | ⬜ | ⬜ |
| Lightning | ⬜ | ⬜ | ⬜ | ⬜ |
| Magnitude | ⬜ | ⬜ | ⬜ | ⬜ |
| NOAA_CIMSS | ⬜ | ⬜ | ⬜ | ⬜ |
| Pilot_Report | ⬜ | ⬜ | ⬜ | ⬜ |
| RSAM | ⬜ | ⬜ | ⬜ | ⬜ |
| SO2 | ⬜ | ⬜ | ⬜ | ⬜ |
| Swarm | ⬜ | ⬜ | ⬜ | ⬜ |
| Tremor | ⬜ | ⬜ | ⬜ | ⬜ |
| VAA | ⬜ | ⬜ | ⬜ | ⬜ |

### scripts

| Script | Unit test file | Status |
|--------|----------------|--------|
| `run_alarm.py` (CLI) | `scripts/test_run_alarm_cli.py` | ⬜ |
