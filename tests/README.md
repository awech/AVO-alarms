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

This maps each part of `volc_alarms` to the test(s) that exercise it. Legend:

- ✅ **unit** — has dedicated unit tests for its pure logic
- 🔄 **integration** — exercised end to end via the alarm's `run_alarm` baseline
  (and/or the harness smoke tests), not as isolated units
- N/A — no standalone unit-level logic to test (thin wrapper, or the whole
  behavior only makes sense end to end)

Every `run_alarm` pipeline has an integration baseline, but the baselines differ
in **how deep into the pipeline they reach** — see "Integration baseline depth"
below before relying on the alarms table. Unit tests focus on the pure logic
(parsing, math, thresholds, message formatting). Network/DB/email/matplotlib
boundaries are deliberately left to the integration layer, so `figure.py` and
the network `download_*` helpers are integration-only.

### utils

| Module | Unit tests | Notes |
|--------|-----------|-------|
| `alarming` | ✅ `utils/test_alarming.py` | DB/rate-limit logic against a temp sqlite; operator CLI list/remove helpers left as TODO |
| `processing` | ✅ `utils/test_processing.py` | geodesy, volcano lookup, stream preprocessing; FDSN-backed `Dr_to_RSAM`/`eq_picks_to_dataframe` are integration-only |
| `messaging` | ✅ `utils/test_messaging.py` | pure formatting + `send=False` short-circuits; live SMTP/Mattermost send paths are integration-only |
| `setup_utils` | ✅ `utils/test_setup_utils.py` | config parse, math-expr eval, path/tz detection, volcano-list loading |
| `plotting` | ✅ `utils/test_plotting.py` | pure geometry/tick math; cartopy/spectrogram rendering is integration-only |
| `downloading` | ✅ `utils/test_downloading.py` | trace QC + HTTP retry wrappers (mocked `requests`); FDSN/Winston waveform fetch is integration-only |
| `alarm_flow` | ✅ `utils/test_alarm_flow.py` | cron-latency backup + the shared CRITICAL send sequence |

### alarms

| Alarm | detection | message | figure | run_alarm (integration depth) |
|-------|-----------|---------|--------|-------------------------------|
| Infrasound | ✅ | N/A (inline) | 🔄 | 🟡 early-exit only |
| Lightning | ✅ | ✅ | 🔄 | 🟢 full send + 🟡 early-exit |
| Magnitude | ✅ | 🔄 (via `process_event`) | 🔄 | 🟢 full send + ⚪ no-op OK |
| NOAA_CIMSS | ✅ | 🔄 | 🔄 | 🟡 early-exit only |
| Pilot_Report | ✅ | 🔄 | 🔄 | ⚪ no-op OK only |
| RSAM | ✅ | ✅ | 🔄 | 🟢 full send + 🟡 early-exit |
| SO2 | ✅ (offline path) | 🔄 | 🔄 | 🟡 early-exit only |
| Swarm | ✅ | 🔄 | 🔄 | ⚪ no-op OK only |
| Tremor | ✅ | 🔄 | 🔄 | 🟡 early-exit only |
| VAA | ✅ | ✅ | ✅ | 🟡 early-exit only |

Unit-test columns (`detection`/`message`/`figure`) live in
`tests/alarms/<Alarm>/test_*.py`; ✅ = dedicated unit tests, 🔄 = exercised only
via the integration baseline, N/A (inline) = the alarm builds its message inside
`run_alarm` rather than a separate `message.py`.

#### Integration baseline depth (important)

The `run_alarm` column reports **how much of the pipeline the frozen baseline
actually reaches**, because this is uneven across alarms and the format alone
does not reveal it:

- 🟢 **full send** — the scenario feeds crafted fixtures that trigger a real
  CRITICAL detection and the complete send sequence (figure → Mattermost →
  email → DB record → cleanup → Icinga). This is the strongest regression guard.
  Alarms: **RSAM**, **Lightning**, **Magnitude** (all have a `_critical` scenario).
- ⚪ **no-op OK** — the scenario reaches a genuine "nothing to report" OK result
  that the alarm is designed to produce (empty catalog / no new reports). The
  decision logic runs; there is just no event. Alarms: **Pilot_Report**,
  **Swarm**, **Magnitude** (representative).
- 🟡 **early-exit only** — the scenario feeds no usable input, so the alarm bails
  at an input guard (missing data / not-enough-channels / API or webpage error)
  and returns WARNING **before its detection logic runs**. These baselines verify
  the plumbing and the guard, **not** the science. Alarms with *only* this depth:
  **Infrasound**, **NOAA_CIMSS**, **SO2**, **Tremor**, **VAA**.

For the 🟡 alarms, the detection science is instead covered by the `detection`
unit tests (e.g. VAA `process_polygons`, Infrasound `filter_lts_results`, Swarm
clustering). The remaining gap is that no *end-to-end* baseline drives those
alarms through a real detection + send. Building those requires crafting
realistic fake inputs per alarm (multi-channel array data, scraped HTML pages,
FDSN XML) and is a known follow-up — see "Extending coverage" below.

#### Extending coverage (known follow-ups)

- Add a `_critical` (real-detection) scenario for the 🟡 alarms so their
  `run_alarm` baseline exercises detection + send, not just an input guard.
  Cheaper candidates first (Tremor, VAA); HTML-scraper alarms (NOAA_CIMSS, SO2)
  are the most fixture-heavy.
- Add unit tests for the remaining `scripts/*` entry points.
- Unit-test the FDSN-backed helpers (`Dr_to_RSAM`, `eq_picks_to_dataframe`) with
  a mocked client.

### scripts

| Script | Unit tests | Notes |
|--------|-----------|-------|
| `run_alarm.py` (CLI) | ✅ `scripts/test_run_alarm_cli.py` | arg parsing, time defaulting, cron/lock/kill-switch/dispatch/error branches |
| others (`dr_to_rsam`, `list_alerts`, `update_metadata`, …) | — | not yet covered; scheduled for a later pass |

> Note: `tests/make_map.py` is a pre-existing standalone plotting example, not a
> pytest test (no `test_` prefix, not collected).
