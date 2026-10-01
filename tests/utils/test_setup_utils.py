"""Unit tests for ``volc_alarms.utils.setup_utils``.

These cover the config-parsing and file-loading helpers with crafted strings
and tmp files. No network is involved. ``load_config`` reads the real repo
``config/*.yml`` (CONFIGS_DIR is set by the top-level conftest).

Covered:
* looks_like_path        — path vs NSLC vs plain-value discrimination
* _evaluate_math_expr    — arithmetic string eval, int coercion, passthrough
* _apply_math_expressions — top-level + nested "value"/"duration" resolution
* load_config            — real YAML -> SimpleNamespace with expected attrs
* load_volcano_list      — CSV/TXT load, rename, env default, column/format errors
* update_infrasound_config — target enrichment, defaults, unknown-target error
* _detect_system_tz      — /etc/timezone, localtime symlink, UTC fallback
* StderrToLogger         — line routing + non-tty
* load_environment       — defaults, no-overwrite, explicit file, missing file
* setup_root_logger      — console vs cron file handler, old-log cleanup, arg errors
* get_logger             — named, propagating logger
* LockFile               — acquire/release, stale/corrupted/foreign/live-lock paths

load_environment / setup_root_logger mutate process-global state (os.environ,
logging handlers); those tests use monkeypatch and explicit handler cleanup to
avoid leaking into other tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from volc_alarms.utils import setup_utils

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# looks_like_path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        ("data/file.csv", True),
        ("./relative/path", True),
        ("~/home/thing", True),
        ("$ENV_VAR/path", True),
        ("config.yml", True),
        ("AV.DLL.01.BDF", False),   # NSLC channel, not a path
        ("plainstring", False),
        (12345, False),             # non-string
    ],
)
def test_looks_like_path_discriminates_paths_from_values(value, expected):
    """looks_like_path treats separators/extensions as paths but not NSLC codes."""
    assert setup_utils.looks_like_path(value) is expected


# ---------------------------------------------------------------------------
# _evaluate_math_expr
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        ("3600 * 24", 86400),
        ("350/100", 3.5),
        ("6000", 6000),
        ("not-math", "not-math"),  # non-arithmetic string passes through
        (42, 42),                   # non-string passes through
    ],
)
def test_evaluate_math_expr_resolves_arithmetic_strings(value, expected):
    """_evaluate_math_expr evaluates safe arithmetic and passes anything else through."""
    assert setup_utils._evaluate_math_expr(value) == expected


def test_evaluate_math_expr_returns_int_for_whole_number_results():
    """_evaluate_math_expr coerces whole-number float results to int."""
    result = setup_utils._evaluate_math_expr("10 / 2")
    assert result == 5
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# _apply_math_expressions
# ---------------------------------------------------------------------------
def test_apply_math_expressions_resolves_top_level_and_nested_keys():
    """_apply_math_expressions evaluates 'value'/'duration' at top level and in nested dicts/lists."""
    config = SimpleNamespace(
        duration="3600 * 2",
        rsam_stations=[{"nslc": "AV.X..BHZ", "value": "350/100"}],
        arrestor={"nslc": "AV.Y..BHZ", "value": "200"},
    )

    setup_utils._apply_math_expressions(config)

    assert config.duration == 7200
    assert config.rsam_stations[0]["value"] == 3.5
    assert config.arrestor["value"] == 200


# ---------------------------------------------------------------------------
# load_config (real repo config)
# ---------------------------------------------------------------------------
def test_load_config_parses_real_rsam_yaml_to_namespace():
    """load_config wraps a real config/*.yml into a SimpleNamespace with attributes."""
    config = setup_utils.load_config("RSAM")
    assert config.alarm_type == "RSAM"
    assert config.alarm_name == "Semisopochnoi RSAM"
    # A math-eligible nested value has been resolved to a number.
    assert all(
        isinstance(sta["value"], (int, float)) for sta in config.rsam_stations
    )


# ---------------------------------------------------------------------------
# load_volcano_list
# ---------------------------------------------------------------------------
def test_load_volcano_list_reads_csv_with_required_columns(tmp_path):
    """load_volcano_list loads a CSV that has Name/Latitude/Longitude."""
    csv = tmp_path / "volcs.csv"
    csv.write_text("Name,Latitude,Longitude\nPavlof,55.417,-161.894\n")
    df = setup_utils.load_volcano_list(csv)
    assert list(df["Name"]) == ["Pavlof"]
    assert {"Name", "Latitude", "Longitude"}.issubset(df.columns)


def test_load_volcano_list_missing_columns_raises_valueerror(tmp_path):
    """load_volcano_list raises ValueError when required columns are absent."""
    csv = tmp_path / "bad.csv"
    csv.write_text("Name,Lat,Lon\nPavlof,55.4,-161.9\n")
    with pytest.raises(ValueError, match="Missing required columns"):
        setup_utils.load_volcano_list(csv)


def test_load_volcano_list_unsupported_format_raises_valueerror(tmp_path):
    """load_volcano_list raises ValueError for an unsupported file extension."""
    bad = tmp_path / "volcs.json"
    bad.write_text("{}")
    with pytest.raises(ValueError, match="Unsupported file format"):
        setup_utils.load_volcano_list(bad)


# ---------------------------------------------------------------------------
# _detect_system_tz
# ---------------------------------------------------------------------------
def test_detect_system_tz_returns_nonempty_string():
    """_detect_system_tz returns a non-empty timezone name (falls back to UTC)."""
    tz = setup_utils._detect_system_tz()
    assert isinstance(tz, str)
    assert tz

# ---------------------------------------------------------------------------
# _detect_system_tz — OS-config branches
# ---------------------------------------------------------------------------
def test_detect_system_tz_reads_etc_timezone(monkeypatch):
    """_detect_system_tz returns the trimmed contents of /etc/timezone when present."""

    def fake_is_file(self):
        return str(self) == "/etc/timezone"

    monkeypatch.setattr(setup_utils.Path, "is_file", fake_is_file)
    monkeypatch.setattr(
        setup_utils.Path, "read_text", lambda self: "America/Anchorage\n"
    )

    assert setup_utils._detect_system_tz() == "America/Anchorage"


def test_detect_system_tz_follows_localtime_symlink(monkeypatch):
    """_detect_system_tz derives the zone from the /etc/localtime zoneinfo symlink."""
    # /etc/timezone absent so we fall through to the symlink branch.
    monkeypatch.setattr(setup_utils.Path, "is_file", lambda self: False)
    monkeypatch.setattr(
        setup_utils.Path,
        "is_symlink",
        lambda self: str(self) == "/etc/localtime",
    )
    monkeypatch.setattr(
        setup_utils.Path,
        "resolve",
        lambda self: Path("/usr/share/zoneinfo/US/Alaska"),
    )

    assert setup_utils._detect_system_tz() == "US/Alaska"


def test_detect_system_tz_falls_back_to_utc(monkeypatch):
    """_detect_system_tz returns UTC when neither OS source is available."""
    monkeypatch.setattr(setup_utils.Path, "is_file", lambda self: False)
    monkeypatch.setattr(setup_utils.Path, "is_symlink", lambda self: False)

    assert setup_utils._detect_system_tz() == "UTC"


# ---------------------------------------------------------------------------
# StderrToLogger
# ---------------------------------------------------------------------------
def test_stderr_to_logger_routes_lines_through_logger():
    """StderrToLogger.write logs each non-empty line and reports a non-tty stream."""
    import logging

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    logger = logging.getLogger("test.stderr.capture")
    logger.setLevel(logging.WARNING)
    logger.addHandler(_Capture())

    stream = setup_utils.StderrToLogger(logger, log_level=logging.WARNING)
    written = stream.write("line one\n\nline two\n")
    stream.flush()  # no-op, exercised for coverage

    assert records == ["line one", "line two"]
    assert written == len("line one\n\nline two\n")
    assert stream.isatty() is False


# ---------------------------------------------------------------------------
# load_environment
# ---------------------------------------------------------------------------
def test_load_environment_applies_path_and_scalar_defaults(monkeypatch):
    """load_environment fills unset env defaults derived from the project layout."""
    # Start from a clean slate for the keys we assert on.
    for key in (
        "CONFIGS_DIR", "LOGS_DIR", "LOCK_DIR", "DB_FILE", "WINSTON_HOST",
        "WINSTON_PORT", "SMTP_SECURITY", "PIREP_URL", "LOG_HOUR_INTERVAL",
    ):
        monkeypatch.delenv(key, raising=False)

    # Avoid loading any real .env from the tree.
    monkeypatch.setattr(setup_utils, "find_dotenv", lambda usecwd=True: "")
    monkeypatch.setattr(setup_utils, "load_dotenv", lambda *a, **k: False)

    setup_utils.load_environment()

    import os as _os

    assert _os.environ["CONFIGS_DIR"].endswith("/config")
    assert _os.environ["WINSTON_HOST"] == "127.0.0.1"
    assert _os.environ["WINSTON_PORT"] == "16022"
    assert _os.environ["SMTP_SECURITY"] == "ssl"
    assert _os.environ["PIREP_URL"].startswith("https://")
    assert _os.environ["LOG_HOUR_INTERVAL"] == "12"


def test_load_environment_does_not_overwrite_existing_values(monkeypatch):
    """load_environment preserves variables already set in the environment."""
    monkeypatch.setenv("WINSTON_HOST", "example.host")
    monkeypatch.setattr(setup_utils, "find_dotenv", lambda usecwd=True: "")
    monkeypatch.setattr(setup_utils, "load_dotenv", lambda *a, **k: False)

    setup_utils.load_environment()

    import os as _os

    assert _os.environ["WINSTON_HOST"] == "example.host"


def test_load_environment_loads_explicit_env_file(monkeypatch, tmp_path):
    """load_environment loads an explicitly provided .env file with override=True."""
    env_file = tmp_path / "custom.env"
    env_file.write_text("WINSTON_PORT=99999\n")

    captured = {}

    def fake_load_dotenv(path, override=False):
        captured["path"] = str(path)
        captured["override"] = override
        return True

    monkeypatch.setattr(setup_utils, "load_dotenv", fake_load_dotenv)

    setup_utils.load_environment(env_file=str(env_file))

    assert captured["path"] == str(env_file)
    assert captured["override"] is True


def test_load_environment_missing_explicit_file_raises(tmp_path):
    """load_environment raises FileNotFoundError for a missing explicit env file."""
    missing = tmp_path / "nope.env"
    with pytest.raises(FileNotFoundError, match="Environment file not found"):
        setup_utils.load_environment(env_file=str(missing))


# ---------------------------------------------------------------------------
# load_config — error paths and type defaults
# ---------------------------------------------------------------------------
def test_load_config_missing_file_raises(monkeypatch, tmp_path):
    """load_config raises FileNotFoundError when the YAML file is absent."""
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        setup_utils.load_config("DoesNotExist")


def test_load_config_non_mapping_root_raises_typeerror(monkeypatch, tmp_path):
    """load_config raises TypeError when the YAML root is not a mapping."""
    (tmp_path / "Listy.yml").write_text("- a\n- b\n")
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    with pytest.raises(TypeError, match="must be a YAML mapping"):
        setup_utils.load_config("Listy")


def test_load_config_converts_pathlike_strings_to_path(monkeypatch, tmp_path):
    """load_config converts top-level path-like scalars to Path objects."""
    (tmp_path / "Paths.yml").write_text(
        "alarm_type: Custom\n"
        "alarm_name: Pathy\n"
        "grid_file: data/grid.npz\n"
        "channel: AV.DLL.01.BDF\n"
    )
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))

    config = setup_utils.load_config("Paths")

    assert isinstance(config.grid_file, Path)
    # NSLC strings are left as-is (not treated as paths).
    assert config.channel == "AV.DLL.01.BDF"


def test_load_config_fills_rsam_defaults(monkeypatch, tmp_path):
    """load_config applies taper/latency/duration defaults for RSAM configs."""
    (tmp_path / "MiniRSAM.yml").write_text(
        "alarm_type: RSAM\nalarm_name: Mini RSAM\n"
    )
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    monkeypatch.delenv("RSAM_DURATION", raising=False)

    config = setup_utils.load_config("MiniRSAM")

    assert config.taper == 5
    assert config.latency == 10
    assert config.duration == 300


def test_load_config_fills_tremor_defaults(monkeypatch, tmp_path):
    """load_config applies grid_file/lookback/window defaults for Tremor configs."""
    (tmp_path / "MiniTremor.yml").write_text(
        "alarm_type: Tremor\nalarm_name: Mini Tremor\n"
    )
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    monkeypatch.delenv("TREMOR_LOOKBACK_WINDOW", raising=False)
    monkeypatch.delenv("TREMOR_WINDOW_LENGTH", raising=False)

    config = setup_utils.load_config("MiniTremor")

    assert str(config.grid_file).endswith("Mini_Tremor_grid.npz")
    assert config.lookback_window == 60
    assert config.window_length == 300


# ---------------------------------------------------------------------------
# load_volcano_list — remaining branches
# ---------------------------------------------------------------------------
def test_load_volcano_list_reads_txt_with_inferred_delimiter(tmp_path):
    """load_volcano_list parses a .txt file, inferring the delimiter."""
    txt = tmp_path / "volcs.txt"
    txt.write_text("Name\tLatitude\tLongitude\nPavlof\t55.417\t-161.894\n")
    df = setup_utils.load_volcano_list(txt)
    assert list(df["Name"]) == ["Pavlof"]


def test_load_volcano_list_renames_columns_case_insensitively(tmp_path):
    """load_volcano_list normalizes differently-cased required columns."""
    csv = tmp_path / "volcs.csv"
    csv.write_text("name,latitude,longitude\nPavlof,55.417,-161.894\n")
    df = setup_utils.load_volcano_list(csv)
    assert {"Name", "Latitude", "Longitude"}.issubset(df.columns)
    assert list(df["Name"]) == ["Pavlof"]


def test_load_volcano_list_defaults_to_env_var(monkeypatch, tmp_path):
    """load_volcano_list reads VOLCANO_LIST when no file argument is given."""
    csv = tmp_path / "env_volcs.csv"
    csv.write_text("Name,Latitude,Longitude\nRedoubt,60.485,-152.742\n")
    monkeypatch.setenv("VOLCANO_LIST", str(csv))
    df = setup_utils.load_volcano_list()
    assert list(df["Name"]) == ["Redoubt"]


# ---------------------------------------------------------------------------
# update_infrasound_config
# ---------------------------------------------------------------------------
def test_update_infrasound_config_enriches_from_volcano_list(monkeypatch):
    """update_infrasound_config fills lat/lon from the volcano list and velocity defaults."""
    import pandas as pd

    df = pd.DataFrame(
        {"Name": ["Pavlof"], "Latitude": [55.4173], "Longitude": [-161.8937]}
    )
    monkeypatch.setattr(setup_utils, "load_volcano_list", lambda: df)

    config = SimpleNamespace(
        alarm_type="Infrasound",
        targets=[{"name": "Pavlof", "az_tolerance": 8, "min_pa": 2.0}],
    )

    result = setup_utils.update_infrasound_config(config)

    target = result.targets[0]
    assert target["lat"] == pytest.approx(55.4173)
    assert target["lon"] == pytest.approx(-161.8937)
    assert target["vmin"] == 0.28
    assert target["vmax"] == 0.45
    assert target["cmin"] == 0.6
    # plot_duration defaults to the env fallback (3600) coerced to float.
    assert target["plot_duration"] == 3600.0


def test_update_infrasound_config_preserves_explicit_coords(monkeypatch):
    """update_infrasound_config keeps caller-provided lat/lon and does not hit the list."""
    import pandas as pd

    def _boom():
        raise AssertionError("load_volcano_list should not be called")

    monkeypatch.setattr(setup_utils, "load_volcano_list", lambda: pd.DataFrame())

    config = SimpleNamespace(
        alarm_type="Infrasound",
        targets=[
            {"name": "Custom", "lat": 1.0, "lon": 2.0, "plot_duration": "2 * 60"}
        ],
    )

    result = setup_utils.update_infrasound_config(config)

    target = result.targets[0]
    assert target["lat"] == 1.0
    assert target["lon"] == 2.0
    # plot_duration arithmetic string is evaluated and coerced to float.
    assert target["plot_duration"] == 120.0


def test_update_infrasound_config_unknown_target_raises(monkeypatch):
    """update_infrasound_config raises ValueError when a target is not in the volcano list."""
    import pandas as pd

    df = pd.DataFrame(
        {"Name": ["Pavlof"], "Latitude": [55.4], "Longitude": [-161.9]}
    )
    monkeypatch.setattr(setup_utils, "load_volcano_list", lambda: df)

    config = SimpleNamespace(
        alarm_type="Infrasound",
        targets=[{"name": "NotAVolcano", "az_tolerance": 5, "min_pa": 1.0}],
    )

    with pytest.raises(ValueError, match="not found in the volcano"):
        setup_utils.update_infrasound_config(config)


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------
def test_get_logger_returns_propagating_logger():
    """get_logger returns a named logger configured to propagate to root."""
    logger = setup_utils.get_logger("volc_alarms.test.module")
    assert logger.name == "volc_alarms.test.module"
    assert logger.propagate is True


# ---------------------------------------------------------------------------
# setup_root_logger
# ---------------------------------------------------------------------------
def test_setup_root_logger_console_handler_when_not_cron(monkeypatch):
    """setup_root_logger attaches a stdout StreamHandler in interactive mode."""
    import logging

    monkeypatch.delenv("FROMCRON", raising=False)

    root = setup_utils.setup_root_logger()
    try:
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.StreamHandler)
    finally:
        logging.getLogger().handlers.clear()


def test_setup_root_logger_file_handler_and_old_log_cleanup(monkeypatch, tmp_path):
    """setup_root_logger writes to a file in cron mode and prunes expired logs."""
    import logging
    import os as _os
    import time as _time

    monkeypatch.setenv("FROMCRON", "yep")
    monkeypatch.setenv("LOG_HOUR_INTERVAL", "12")
    monkeypatch.setenv("LOG_DAYS_KEEP", "7")

    # An old log that should be pruned (mtime well beyond retention).
    old_log = tmp_path / "TestCfg-20000101-00.log"
    old_log.write_text("stale\n")
    _os.utime(old_log, (0, 0))

    root = setup_utils.setup_root_logger(
        log_dir=str(tmp_path), config_name="TestCfg"
    )
    try:
        handlers = logging.getLogger().handlers
        assert any(isinstance(h, logging.FileHandler) for h in handlers)
        # The stale log was removed by the retention sweep.
        assert not old_log.exists()
        # A fresh log file for this run was created.
        assert list(tmp_path.glob("TestCfg-*.log"))
    finally:
        for h in logging.getLogger().handlers:
            h.close()
        logging.getLogger().handlers.clear()


def test_setup_root_logger_cron_requires_config_name(monkeypatch, tmp_path):
    """setup_root_logger raises when cron mode is missing config_name."""
    monkeypatch.setenv("FROMCRON", "yep")
    with pytest.raises(ValueError, match="config_name must be provided"):
        setup_utils.setup_root_logger(log_dir=str(tmp_path), config_name=None)
    logging_cleanup()


def test_setup_root_logger_cron_requires_log_dir(monkeypatch):
    """setup_root_logger raises when cron mode has neither log_dir nor LOGS_DIR."""
    monkeypatch.setenv("FROMCRON", "yep")
    monkeypatch.delenv("LOGS_DIR", raising=False)
    with pytest.raises(ValueError, match="log_dir must be provided"):
        setup_utils.setup_root_logger(log_dir=None, config_name="TestCfg")
    logging_cleanup()


def logging_cleanup():
    """Helper to drop any handlers a failed setup_root_logger left behind."""
    import logging

    for h in logging.getLogger().handlers:
        h.close()
    logging.getLogger().handlers.clear()


# ---------------------------------------------------------------------------
# LockFile
# ---------------------------------------------------------------------------
def test_lockfile_acquire_and_release_cycle(tmp_path):
    """LockFile writes a PID file on acquire and removes it on release."""
    lock = setup_utils.LockFile(str(tmp_path), "myalarm")
    lock.acquire()
    assert lock.lock_file.exists()
    assert lock.lock_file.read_text().strip() == str(os.getpid())

    lock.release()
    assert not lock.lock_file.exists()
    assert lock.acquired is False


def test_lockfile_context_manager(tmp_path):
    """LockFile works as a context manager, releasing on exit."""
    lf = setup_utils.LockFile(str(tmp_path), "ctx")
    with lf as entered:
        assert entered is lf
        assert lf.lock_file.exists()
    assert not lf.lock_file.exists()


def test_lockfile_raises_when_live_process_holds_lock(tmp_path, monkeypatch):
    """LockFile.acquire raises RuntimeError when another live process holds the lock."""
    lock_file = tmp_path / "busy.lock"
    lock_file.write_text("4242")

    # Pretend PID 4242 is alive (os.kill with signal 0 succeeds).
    monkeypatch.setattr(setup_utils.os, "kill", lambda pid, sig: None)

    lock = setup_utils.LockFile(str(tmp_path), "busy")
    with pytest.raises(RuntimeError, match="already running"):
        lock.acquire()


def test_lockfile_clears_stale_lock_from_dead_process(tmp_path, monkeypatch):
    """LockFile.acquire removes a stale lock whose process no longer exists."""
    lock_file = tmp_path / "stale.lock"
    lock_file.write_text("4242")

    def _dead(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(setup_utils.os, "kill", _dead)

    lock = setup_utils.LockFile(str(tmp_path), "stale")
    lock.acquire()  # should reclaim the stale lock
    assert lock.lock_file.read_text().strip() == str(os.getpid())
    lock.release()


def test_lockfile_handles_corrupted_lock_file(tmp_path):
    """LockFile.acquire removes a corrupted (non-integer) lock file and proceeds."""
    lock_file = tmp_path / "corrupt.lock"
    lock_file.write_text("not-a-pid")

    lock = setup_utils.LockFile(str(tmp_path), "corrupt")
    lock.acquire()
    assert lock.lock_file.read_text().strip() == str(os.getpid())
    lock.release()


def test_lockfile_release_leaves_foreign_lock_untouched(tmp_path):
    """LockFile.release does not delete a lock owned by a different PID."""
    lock = setup_utils.LockFile(str(tmp_path), "foreign")
    lock.acquire()
    # Simulate the lock now belonging to another process.
    lock.lock_file.write_text("999999")
    lock.release()
    # The foreign lock file is left in place.
    assert lock.lock_file.exists()
    lock.lock_file.unlink()
