"""Unit tests for the ``update-metadata`` command-line entry point.

Cover the lock-held early return and the success path that refreshes the station
XML, with the lock, logging, env, and ``download_station_xml`` all mocked (no
network).

Covered:
* main() — aborts without downloading when the lock is held
* main() — calls download_station_xml and releases the lock on the happy path
"""

from __future__ import annotations

import sys

import pytest

from volc_alarms.scripts import update_metadata as cli

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
    """Mock env/logging/lock and count download_station_xml calls."""
    _FakeLock.instances = []
    downloads = []

    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(cli, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(cli, "LockFile", _FakeLock)
    monkeypatch.setattr(cli, "download_station_xml", lambda: downloads.append(True))
    monkeypatch.delenv("FROMCRON", raising=False)
    monkeypatch.setattr(sys, "argv", ["update-metadata"])
    return downloads


def test_main_returns_early_when_lock_held(wired, monkeypatch):
    """main() does not download when the lock is held."""
    orig_init = _FakeLock.__init__

    def _init(self, *a, **k):
        orig_init(self, *a, **k)
        self.raise_on_acquire = True

    monkeypatch.setattr(_FakeLock, "__init__", _init)

    cli.main()
    assert wired == []


def test_main_downloads_station_xml_and_releases_lock(wired):
    """main() refreshes the station XML and releases the lock on the happy path."""
    cli.main()

    assert wired == [True]
    assert _FakeLock.instances[0].released is True
