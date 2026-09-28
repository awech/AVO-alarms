"""Unit tests for the ``generic-alarm`` command-line entry point.

Cover argument parsing and the ``main()`` path that sets an alarm's Icinga
service to OK, with the lock, logging, env, and ``icinga`` all mocked.

Covered:
* parse_args — required alarm-name positional
* main()     — lock-held early return
* main()     — sets Icinga OK for the (underscore-expanded) alarm name
"""

from __future__ import annotations

import sys

import pytest

from volc_alarms.scripts import generic_alarm as cli

pytestmark = pytest.mark.unit


class _FakeLock:
    instances = []

    def __init__(self, lock_dir, config_name, timeout=300):
        self.config_name = config_name
        self.released = False
        self.raise_on_acquire = False
        _FakeLock.instances.append(self)

    def acquire(self):
        if self.raise_on_acquire:
            raise RuntimeError("already running")

    def release(self):
        self.released = True


@pytest.fixture
def wired(monkeypatch):
    """Mock env/logging/lock and capture icinga calls."""
    _FakeLock.instances = []
    icinga_calls = []

    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(cli, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(cli, "LockFile", _FakeLock)
    monkeypatch.setattr(
        cli, "icinga",
        lambda config, state, msg, send=True: icinga_calls.append((config.alarm_name, state, msg)),
    )
    monkeypatch.delenv("FROMCRON", raising=False)
    return icinga_calls


def test_parse_args_requires_alarm_name(monkeypatch):
    """parse_args reads the required positional alarm name."""
    monkeypatch.setattr(sys, "argv", ["generic-alarm", "Pavlof_RSAM"])
    assert cli.parse_args().alarm == "Pavlof_RSAM"


def test_main_returns_early_when_lock_held(wired, monkeypatch):
    """main() does not touch Icinga when the lock is held."""
    orig_init = _FakeLock.__init__

    def _init(self, *a, **k):
        orig_init(self, *a, **k)
        self.raise_on_acquire = True

    monkeypatch.setattr(_FakeLock, "__init__", _init)
    monkeypatch.setattr(sys, "argv", ["generic-alarm", "Pavlof_RSAM"])

    cli.main()
    assert wired == []


def test_main_sets_icinga_ok_for_alarm(wired, monkeypatch):
    """main() sets the alarm's Icinga service to OK with an empty-service message."""
    monkeypatch.setattr(sys, "argv", ["generic-alarm", "Pavlof_RSAM"])

    cli.main()

    assert len(wired) == 1
    alarm_name, state, msg = wired[0]
    assert alarm_name == "Pavlof RSAM"   # underscores expanded to spaces
    assert state == "OK"
    assert msg == "Empty alarm service"
    assert _FakeLock.instances[0].released is True
