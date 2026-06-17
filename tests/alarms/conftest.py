"""Pytest fixtures for the alarm behavior-preservation harness.

Establishes the offline, deterministic environment the golden behavior tests
need:

* points ``CONFIGS_DIR`` at the in-repo ``config/`` directory and loads real
  config objects through ``setup_utils.load_config`` (configs are *not* mocked --
  Req 10.1), so ``run_alarm`` is driven with genuine config data;
* installs the shared test doubles (see ``doubles.py``) that replace every
  external side effect (Req 12.1);
* provides a helper to set ``FROMCRON`` per test.

``setup_utils.load_config`` reads the ``config/*.yml`` files exclusively.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from importlib.resources import files

from tests.alarms.doubles import AlarmDoubles, CallRecorder, FakeAlarmDB, install

# Repo root is two levels up from tests/alarms/.
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = files("volc_alarms.data")

# ---------------------------------------------------------------------------
# Environment setup (applied at import so it is in place before any volc_alarms
# module that reads these vars at call time runs).
# ---------------------------------------------------------------------------
# Drive run_alarm with the real .yml config files checked into the repo.
os.environ["CONFIGS_DIR"] = str(CONFIG_DIR)
os.environ.setdefault("HOME_DIR", str(REPO_ROOT))
# Keep the harness self-contained: point data files at in-repo copies / temp.
os.environ.setdefault("VOLCANO_LIST", str(DATA_DIR.joinpath("volcano_list.xlsx")))
os.environ.setdefault("TMP_FIGURE_DIR", str(REPO_ROOT / "tmp_files"))
os.environ.setdefault("TIMEZONE", "UTC")
# FDSN base URL used by the Swarm alarm to build its (mocked) download request.
os.environ.setdefault("FDSN_URL", "https://service.example.com/fdsnws/event/1/query?")
# Never touch a real alarm-history DB; the DB doubles are in-memory regardless.
os.environ.setdefault("DB_FILE", str(REPO_ROOT / "tmp_files" / "__test_alarms__.db"))
# Make sure no test accidentally runs as if launched from cron unless it asks.
os.environ.pop("FROMCRON", None)


@pytest.fixture
def recorder() -> CallRecorder:
    """A fresh ordered call recorder for the test."""
    return CallRecorder()


@pytest.fixture
def fake_db() -> FakeAlarmDB:
    """A fresh in-memory alarm-history store for the test."""
    return FakeAlarmDB()


@pytest.fixture
def fromcron(monkeypatch):
    """Return a setter controlling the ``FROMCRON`` environment variable.

    Usage::

        def test_x(fromcron):
            fromcron("yep")   # simulate a cron launch
            ...
            fromcron(None)    # explicit non-cron
    """

    def _set(value: str | None = "yep") -> None:
        if value is None:
            monkeypatch.delenv("FROMCRON", raising=False)
        else:
            monkeypatch.setenv("FROMCRON", value)

    return _set


@pytest.fixture
def alarm_doubles(monkeypatch, recorder, fake_db) -> AlarmDoubles:
    """Install all shared test doubles and return the configurable handle.

    Replaces every external side effect (downloads, Mattermost, email, Icinga,
    DB access, figure save, ``os.remove``) with recording/canned doubles so an
    alarm's ``run_alarm`` runs offline and deterministically (Req 12.1).
    """
    handle = AlarmDoubles(recorder, fake_db, monkeypatch)
    return install(handle)


@pytest.fixture
def load_alarm_config():
    """Factory that loads a real config module via ``setup_utils.load_config``.

    ``CONFIGS_DIR`` already points at the repo ``config/`` directory, so e.g.
    ``load_alarm_config("RSAM")`` returns the genuine config object that
    ``run_alarm`` expects (Req 10.1, 10.2).
    """
    from volc_alarms.utils import setup_utils

    def _load(config_name: str):
        return setup_utils.load_config(config_name)

    return _load
