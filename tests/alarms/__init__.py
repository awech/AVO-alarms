"""Regression tests for volc_alarms.

Ensures alarm behavior doesn't accidentally change during code changes by:
- Running each alarm offline with fake data (no real network/database calls)
- Recording what each alarm *does* (messages sent, Icinga state, DB writes)
- Comparing against saved "known-good" JSON snapshots

Key modules:
- conftest.py       Test setup and shared fixtures
- fakes.py          Fake replacements for all external services (network, DB, etc.)
- scenarios.py      Test input data + alarm invocations
- snapshot_utils.py Captures alarm outputs and saves/loads JSON snapshots
"""
