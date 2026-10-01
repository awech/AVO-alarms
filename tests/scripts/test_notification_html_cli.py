"""Unit tests for the ``update-html`` (notification HTML) entry point.

Cover the lock-held early return and the success path that renders the
distribution table to an HTML file, with the lock, logging, and env mocked. A
tiny distribution YAML is provided via a temp file; the output path is a temp
file, so no real filesystem locations are touched.

Covered:
* main() — aborts without writing when the lock is held
* main() — writes an HTML notification table from the distribution list
"""

from __future__ import annotations

import sys

import pytest

from volc_alarms.scripts import notification_html as cli

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
def wired(tmp_path, monkeypatch):
    """Mock env/logging/lock; point DISTRIBUTION_FILE/WWW_FILE at temp files."""
    _FakeLock.instances = []

    dist = tmp_path / "distribution.yml"
    dist.write_text(
        "Pavlof RSAM:\n  - alice\n  - bob\n"
        "Cleveland RSAM:\n  - alice\n"
    )
    out = tmp_path / "notifications.html"

    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(cli, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(cli, "LockFile", _FakeLock)
    monkeypatch.setenv("DISTRIBUTION_FILE", str(dist))
    monkeypatch.setenv("WWW_FILE", str(out))
    monkeypatch.delenv("FROMCRON", raising=False)
    monkeypatch.setattr(sys, "argv", ["update-html"])
    return out


def test_main_returns_early_when_lock_held(wired, monkeypatch):
    """main() does not write output when the lock is held."""
    orig_init = _FakeLock.__init__

    def _init(self, *a, **k):
        orig_init(self, *a, **k)
        self.raise_on_acquire = True

    monkeypatch.setattr(_FakeLock, "__init__", _init)

    cli.main()
    assert not wired.exists()


def test_main_writes_html_table_from_distribution(wired):
    """main() renders the distribution list to an HTML table and releases the lock."""
    cli.main()

    assert wired.exists()
    html = wired.read_text()
    assert "<table" in html
    # Recipient names from the distribution list appear as columns.
    assert "alice" in html and "bob" in html
    assert _FakeLock.instances[0].released is True
