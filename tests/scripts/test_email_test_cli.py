"""Unit tests for the ``email-test`` command-line entry point.

Cover the lock-held early return and the success path that sends a test alert,
with the lock, logging, env, and ``send_alert`` all mocked (no SMTP).

Covered:
* main() — aborts without sending when the lock is held
* main() — sends a "Test" alert and releases the lock on the happy path
"""

from __future__ import annotations

import sys

import pytest

from volc_alarms.scripts import email_test as cli

pytestmark = pytest.mark.unit


class _FakeLock:
    instances = []

    def __init__(self, lock_dir, config_name, timeout=300):
        self.lock_dir = lock_dir
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
    """Mock env/logging/lock and capture send_alert calls."""
    _FakeLock.instances = []
    sent = []

    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(cli, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(cli, "LockFile", _FakeLock)
    monkeypatch.setattr(
        cli, "send_alert",
        lambda alarm_name, subject, message, attachment=None, test=False: sent.append(
            (alarm_name, subject)
        ),
    )
    monkeypatch.delenv("FROMCRON", raising=False)
    monkeypatch.setattr(sys, "argv", ["email-test"])
    return sent


def test_main_returns_early_when_lock_held(wired, monkeypatch):
    """main() does not send an alert when the lock cannot be acquired."""
    orig_init = _FakeLock.__init__

    def _init(self, *a, **k):
        orig_init(self, *a, **k)
        self.raise_on_acquire = True

    monkeypatch.setattr(_FakeLock, "__init__", _init)

    cli.main()
    assert wired == []  # no send


def test_main_sends_test_alert_and_releases_lock(wired):
    """main() sends a 'Test' alert and releases the lock on the happy path."""
    cli.main()

    assert len(wired) == 1
    alarm_name, subject = wired[0]
    assert alarm_name == "Test"
    assert subject == "Alarm Email Test"
    assert _FakeLock.instances[0].released is True
