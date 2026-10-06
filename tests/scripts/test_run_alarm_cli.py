"""Unit tests for the ``run-alarm`` command-line entry point.

These cover the CLI's argument handling and the branching in ``main()`` with all
external boundaries mocked: config loading, environment loading, logging setup,
the file lock, the messaging layer, and the dynamic alarm-module import. No
alarm actually runs, no network/DB/email is touched, and no lock file is written.

Covered:
* parse_args        — required config arg + flag defaults
* update_arguments  — --force implies --test; explicit vs default (rounded) time
* main()            — non-cron lock-dir, cron lock-dir, lock-held early return,
                      kill-switch (icinga WARNING + no dispatch), normal dispatch
                      to the right alarm module, and the error path (send_alert)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from obspy import UTCDateTime

from volc_alarms.scripts import run_alarm as cli
from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import (
    load_config as real_load_config,  # noqa: F401  (imported to document the target)
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------
def test_parse_args_requires_config_and_defaults_flags(monkeypatch):
    """parse_args captures the positional config and leaves flags off by default."""
    monkeypatch.setattr(sys, "argv", ["run-alarm", "Pavlof_RSAM"])
    args = cli.parse_args()
    assert args.config == "Pavlof_RSAM"
    assert args.test is False
    assert args.force is False
    assert args.mm is False
    assert args.icinga is False
    assert args.time is None


def test_parse_args_reads_optional_flags(monkeypatch):
    """parse_args reads the --test/--mm/--icinga/--time optional flags."""
    monkeypatch.setattr(
        sys, "argv",
        ["run-alarm", "--test", "--mm", "--icinga", "-t", "201701020205", "Pavlof_RSAM"],
    )
    args = cli.parse_args()
    assert args.test is True
    assert args.mm is True
    assert args.icinga is True
    assert args.time == "201701020205"


# ---------------------------------------------------------------------------
# update_arguments
# ---------------------------------------------------------------------------
def test_update_arguments_force_implies_test():
    """update_arguments sets test=True whenever force is set."""
    args = SimpleNamespace(force=True, test=False, time="201701020205")
    out = cli.update_arguments(args)
    assert out.test is True


def test_update_arguments_parses_explicit_time():
    """update_arguments converts an explicit -t timestamp to a UTCDateTime."""
    args = SimpleNamespace(force=False, test=False, time="201701020205")
    out = cli.update_arguments(args)
    assert out.time == UTCDateTime("201701020205")


def test_update_arguments_defaults_to_current_minute(monkeypatch):
    """update_arguments uses the current UTC time (rounded to the minute) when none is given."""
    import obspy

    fixed = UTCDateTime("2025-01-01T00:30:45")
    monkeypatch.setattr(obspy.UTCDateTime, "utcnow", staticmethod(lambda: fixed))

    args = SimpleNamespace(force=False, test=False, time=None)
    out = cli.update_arguments(args)
    # Seconds are dropped (rounded down to the minute).
    assert out.time == UTCDateTime("2025-01-01T00:30:00")


# ---------------------------------------------------------------------------
# main() — shared wiring
# ---------------------------------------------------------------------------
class _FakeLock:
    """Records acquire/release; optionally raises on acquire (lock held)."""

    instances = []

    def __init__(self, lock_dir, config_name, timeout=300):
        self.lock_dir = lock_dir
        self.config_name = config_name
        self.acquired = False
        self.released = False
        self.raise_on_acquire = False
        _FakeLock.instances.append(self)

    def acquire(self):
        if self.raise_on_acquire:
            raise RuntimeError("already running")
        self.acquired = True

    def release(self):
        self.released = True


@pytest.fixture
def cli_env(monkeypatch):
    """Wire main()'s boundaries with recording doubles; return the recorder.

    Patches on the SOURCE modules that ``main()`` imports from at call time
    (setup_utils.*, messaging.*) plus ``import_module`` on the CLI module.
    """
    from volc_alarms.utils import setup_utils

    rec = {
        "alarm_run": [],
        "icinga": [],
        "send_alert": [],
        "config": SimpleNamespace(alarm_type="RSAM", alarm_name="Pavlof RSAM"),
        "raise_in_alarm": False,
    }

    _FakeLock.instances = []

    monkeypatch.setattr(setup_utils, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(setup_utils, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(setup_utils, "LockFile", _FakeLock)
    monkeypatch.setattr(setup_utils, "load_config", lambda name: rec["config"])

    def _icinga(config, state, msg, send=True):
        rec["icinga"].append((state, msg, send))

    def _send_alert(alarm_name, subject, body, attachment=None, test=False):
        rec["send_alert"].append((alarm_name, subject))

    monkeypatch.setattr(messaging, "icinga", _icinga)
    monkeypatch.setattr(messaging, "send_alert", _send_alert)

    def _fake_import_module(name):
        def _run_alarm(config, T0, **kwargs):
            rec["alarm_run"].append((name, kwargs))
            if rec["raise_in_alarm"]:
                raise ValueError("boom")

        return SimpleNamespace(run_alarm=_run_alarm)

    monkeypatch.setattr(cli, "import_module", _fake_import_module)

    # Default off-cron; individual tests can flip FROMCRON.
    monkeypatch.delenv("FROMCRON", raising=False)
    return rec


def _run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["run-alarm", *argv])
    cli.main()


def test_main_dispatches_to_the_configured_alarm_module(monkeypatch, cli_env):
    """main() imports volc_alarms.alarms.<type> and calls its run_alarm with the flags."""
    _run_cli(monkeypatch, ["--mm", "--icinga", "-t", "201701020205", "Pavlof_RSAM"])

    assert cli_env["alarm_run"] == [
        ("volc_alarms.alarms.RSAM", {"test_flag": False, "mm_flag": True, "icinga_flag": True, "force_flag": False})
    ]
    # Lock acquired and released around the run.
    assert _FakeLock.instances[0].acquired is True
    assert _FakeLock.instances[0].released is True


def test_main_returns_early_when_lock_is_held(monkeypatch, cli_env):
    """main() aborts without dispatching when the alarm lock cannot be acquired."""
    # Make the next LockFile raise on acquire.
    original_init = _FakeLock.__init__

    def _init(self, *a, **k):
        original_init(self, *a, **k)
        self.raise_on_acquire = True

    monkeypatch.setattr(_FakeLock, "__init__", _init)

    _run_cli(monkeypatch, ["Pavlof_RSAM"])

    assert cli_env["alarm_run"] == []  # never dispatched


def test_main_kill_switch_sends_warning_and_skips_dispatch(monkeypatch, cli_env):
    """main() with a kill-switch config sends an Icinga WARNING and does not run the alarm."""
    cli_env["config"] = SimpleNamespace(alarm_type="RSAM", alarm_name="Pavlof RSAM", kill=True)

    _run_cli(monkeypatch, ["--icinga", "Pavlof_RSAM"])

    assert cli_env["alarm_run"] == []
    assert len(cli_env["icinga"]) == 1
    state, msg, _ = cli_env["icinga"][0]
    assert state == "WARNING"
    assert "killed" in msg.lower()
    # Lock was released on the kill-switch path too.
    assert _FakeLock.instances[0].released is True


def test_main_error_path_emails_traceback(monkeypatch, cli_env):
    """main() sends an error alert (and still releases the lock) when the alarm raises."""
    cli_env["raise_in_alarm"] = True

    _run_cli(monkeypatch, ["Pavlof_RSAM"])

    assert len(cli_env["send_alert"]) == 1
    alarm_name, subject = cli_env["send_alert"][0]
    assert alarm_name == "Error"
    assert subject == "Pavlof RSAM error"
    assert _FakeLock.instances[0].released is True


def test_main_uses_home_lock_dir_when_not_cron(monkeypatch, cli_env):
    """Off-cron, main() locks under ~/.tmp/alarms rather than a cron LOGS_DIR."""
    _run_cli(monkeypatch, ["Pavlof_RSAM"])
    lock = _FakeLock.instances[0]
    assert lock.lock_dir == Path.home() / ".tmp" / "alarms"


def test_main_uses_logs_dir_lock_when_cron(monkeypatch, cli_env, tmp_path):
    """On cron (FROMCRON=yep), main() locks under LOGS_DIR (no LOCK_DIR set)."""
    monkeypatch.setenv("FROMCRON", "yep")
    monkeypatch.setenv("LOGS_DIR", str(tmp_path))
    monkeypatch.delenv("LOCK_DIR", raising=False)

    _run_cli(monkeypatch, ["Pavlof_RSAM"])

    lock = _FakeLock.instances[0]
    assert str(lock.lock_dir) == str(tmp_path)
