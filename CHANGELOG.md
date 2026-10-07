# Release Notes

## Versions
To check which version of `volc-alarms` you have installed:
```bash
pip show volc-alarms
```

## Maintenance team

Current and past maintainers of AVO-alarms:

- @awech
- @jlubbers


## [1.0.0] Unreleased

Work toward the first tagged `v1.0.0` of the modern (2026) codebase. This is a
near-complete rewrite of the pre-2026 alarms into an installable
`volc-alarms` package with a shared alarm-run framework, a test suite, and
published documentation.

### ✨ Features

- A unified `run-alarm` entry point for every alarm type, plus a suite of
  helper command-line tools for querying alert history, refreshing station
  metadata, and other routine tasks.
- Multiple notification channels: email/SMS, Icinga heartbeat monitoring, and
  Mattermost posting. Icinga and Mattermost are no longer baked into the alarm
  logic — they are optional integrations enabled per run with simple flags.
- Per-alarm rate limiting to suppress bursts of repeat alerts.
- A per-alarm kill switch to cleanly disable a single alarm without pulling it
  from the schedule.
- An alert history database that records every alert sent, so runs can be
  queried after the fact and used for de-duplication and rate limiting.

### ⚙️ Configuration

- Alarm configuration moved from Python modules to plain YAML files, so
  defining or tuning an alarm no longer requires touching code.
- Config files can live outside the package repository, letting operational
  settings be versioned separately from the source.
- Each alarm is driven by its own config file, with sensible defaults applied
  from config-wide settings and environment variables so a config only needs
  to state what differs from the defaults.
- Notification distribution moved from a spreadsheet (`.xlsx`) to YAML. The
  distribution list carries no personal contact info, so it can live in a
  shared repository, while recipient contact details stay in a separate,
  private phonebook.
- Station metadata is no longer hard-coded. Alarms read channel metadata from
  a StationXML file that is refreshed on demand, so adding or swapping stations
  is a config change rather than a code change.

### 📚 Documentation

- A full documentation site (MkDocs) published via GitLab Pages, including an
  API reference generated directly from the source.
- Comprehensive docstrings throughout the codebase.

### 🛠️ Under the hood

- Reorganized from a collection of scripts into an installable Python package.
- A shared alarm-run framework so every alarm type reuses the same
  data-handling, latency, and notification send sequence instead of
  reimplementing it.
- Single-instance locking is now built into every alarm run, replacing the
  separate external lock script and making each alarm self-contained and
  plug-and-play.
- Proper file logging through a shared logger with rotation, replacing ad-hoc
  print/log handling.
- A CI/CD pipeline that runs the test suite across supported Python versions
  and builds and publishes the documentation.
- Modernized Python version support.

### 🐛 Bugs

- Numerous correctness fixes across the alarm modules surfaced while building
  out the test suite, including time-zone handling and event de-duplication.

### 🧪 Testing

- A full-pipeline test mode (`--test`): any alarm can be run end-to-end against
  a chosen time, exercising detection, figures, and the full notification path
  while routing to test destinations instead of real recipients.
- A full automated test suite with coverage, built around recorded real-world
  scenarios so each alarm's end-to-end behavior is pinned against a known
  baseline.


## v0.1.0 — 2026-08-11

Pre-rewrite baseline. Alarm configs were split out into separate config files
(imported from a separate repository). Tagged immediately before the major
2026 updates. See the git history for details.


## v0.0.0 — 2026-08-11

Initial tag of the legacy alarms, captured before the 2026 updates began.