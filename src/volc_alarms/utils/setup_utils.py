"""
Centralized logging configuration for AVO Alarms package.

Provides setup functions to configure loggers with appropriate handlers
based on whether the code is running from cron or interactively.

When FROMCRON environment variable is set, logs are written to rotating
files (4-hour intervals, 2-week retention). Otherwise, logs go to console.
"""

import glob
import io
import logging
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import yaml
from dotenv import find_dotenv, load_dotenv

# Absolute project root, derived from this file's location:
# src/volc_alarms/utils/setup_utils.py → 3 parents up = project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TMP_DIR = PROJECT_ROOT / "tmp_files"


def load_environment(env_file=None):
    """
    Load environment variables from a .env file and apply sensible defaults.

    After loading the dotenv file, sets defaults for path-based variables that
    can be inferred from the project layout. Variables already set (via .env or
    the shell environment) are never overwritten.

    Args:
        env_file: Optional path to a .env file. If provided, that file is
            loaded and its values override any variables already set in the
            environment. If omitted, the directory tree is searched upward
            for a .env file (the default python-dotenv behavior).

    Raises:
        FileNotFoundError: If an explicit env_file is given but does not exist.
    """
    if env_file:
        env_path = Path(env_file)
        if not env_path.is_file():
            raise FileNotFoundError(f"Environment file not found: {env_path}")
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(find_dotenv(usecwd=True), override=True)

    # Project root derived from package location (stable regardless of cwd):
    # src/volc_alarms/utils/setup_utils.py → 3 parents up = project root
    _project_root = PROJECT_ROOT

    # --- Directory Path defaults (overridden by .env or shell exports) ---
    os.environ.setdefault("CONFIGS_DIR", str(_project_root / "config"))
    os.environ.setdefault("LOGS_DIR", str(_project_root / "logs"))
    os.environ.setdefault("LOCK_DIR", str(_project_root / "locks"))
    os.environ.setdefault("TMP_FIGURE_DIR", str(TMP_DIR))
    
    # --- File Path defaults (overridden by .env or shell exports) ---
    os.environ.setdefault("DB_FILE", str(TMP_DIR / "alarms_sent.db"))
    os.environ.setdefault("DISTRIBUTION_FILE", str(Path(os.environ["CONFIGS_DIR"]) / "distribution.yml"))
    os.environ.setdefault("PHONEBOOK_FILE", str(_project_root / "config" / "phonebook.yml"))
    os.environ.setdefault("VOLCANO_LIST", str(_project_root / "src" / "volc_alarms" / "data" / "volcano_list.csv"))
    os.environ.setdefault("STATION_XML", str(TMP_DIR / "stations.xml"))
    os.environ.setdefault("WWW_FILE", str(TMP_DIR / "index.html"))

    # --- Waveserver defaults (overridden by .env or shell exports) ---
    os.environ.setdefault("WINSTON_HOST", "127.0.0.1")
    os.environ.setdefault("WINSTON_PORT", "16022")
    os.environ.setdefault("TIMEOUT", "20")

    # --- URL defaults (overridden by .env or shell exports) ---
    PIREP_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/pireps.py"
    VAA_URL = "https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json?pil=VAA"
    SACS_URL = "http://sacs.aeronomie.be/lastNOTIFICATION.php"
    os.environ.setdefault("PIREP_URL", PIREP_URL)
    os.environ.setdefault("VAA_URL", VAA_URL)
    os.environ.setdefault("SACS_URL", SACS_URL)

    # --- Non-path defaults ---
    os.environ.setdefault("TIMEZONE", _detect_system_tz())
    os.environ.setdefault("LOG_HOUR_INTERVAL", "12")
    os.environ.setdefault("LOG_DAYS_KEEP", "7")


def _detect_system_tz():
    """Detect the system IANA timezone name from OS config, falling back to UTC.

    Checks:
        1. /etc/timezone (Debian/Ubuntu)
        2. /etc/localtime symlink into a zoneinfo directory (RHEL/macOS)
        3. Falls back to "UTC"

    Returns
    -------
    str
        IANA timezone name.
    """
    _etc_tz = Path("/etc/timezone")
    if _etc_tz.is_file():
        name = _etc_tz.read_text().strip()
        if name:
            return name

    _etc_localtime = Path("/etc/localtime")
    if _etc_localtime.is_symlink():
        _link = str(_etc_localtime.resolve())
        if "zoneinfo/" in _link:
            return _link.split("zoneinfo/", 1)[1]

    return "UTC"


class StderrToLogger(io.TextIOBase):
    """
    Redirect stderr output to a logger.
    
    This captures output from C/FORTRAN libraries (like earthworm) that print 
    directly to stderr, routing it through Python's logging system.
    """
    def __init__(self, logger, log_level=logging.WARNING):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ""

    def write(self, buf):
        """Write buffer to logger."""
        for line in buf.rstrip().splitlines():
            line = line.rstrip()
            if line:
                self.logger.log(self.log_level, line)
        return len(buf)

    def flush(self):
        """Flush (no-op for logger)."""
        pass

    def isatty(self):
        """Return False since we're not a terminal."""
        return False


def looks_like_path(value):
    """Check if a string value looks like a file path."""
    if not isinstance(value, str):
        return False

    # Check for path separators
    if '/' in value or '\\' in value:
        return True

    # Check for relative/home/env var paths
    if value.startswith(('.', '~', '$')):
        return True

    # Check for filename with extension pattern
    # Matches patterns like "file.txt", "config.yml", etc.
    if re.search(r'[a-zA-Z0-9_-]+\.[a-zA-Z0-9]{2,}$', value):
        return True

    return False


def _evaluate_math_expr(value):
    """Evaluate a simple arithmetic string (e.g. '3600 * 24 * 3').

    Supports chained +, -, *, / operations between numeric values.
    Only evaluates strings composed entirely of digits, decimal points,
    whitespace, and arithmetic operators. Returns the numeric result,
    or the original value unchanged if it doesn't match.
    """
    if not isinstance(value, str):
        return value

    safe_math_re = re.compile(r"^[\d\s+\-*/.()]+$")

    if not safe_math_re.match(value):
        return value

    try:
        result = eval(value)  # noqa: S307 — input is validated above
    except (SyntaxError, ZeroDivisionError, TypeError):
        return value

    # Return int when the result is a whole number
    if isinstance(result, float) and result == int(result):
        return int(result)
    return result


def load_config(config_name):
    """
    Load configuration from a YAML file in CONFIGS_DIR.

    Reads CONFIGS_DIR/{config_name}.yml, parses it with ``yaml.safe_load``,
    and wraps the resulting mapping in a ``types.SimpleNamespace`` so that
    top-level keys are exposed as attributes. Top-level scalar strings that
    look like file paths are converted to ``pathlib.Path`` objects; nested
    list/dict members are left as the native parsed YAML types.

    Parameters
    ----------
    config_name : str
        Name of the config file (without .yml extension)

    Returns
    -------
    types.SimpleNamespace
        The parsed config with top-level path strings converted to Path
        objects. When ``alarm_type == "Infrasound"`` the targets are enriched
        via :func:`update_infrasound_config`.

    Raises
    ------
    FileNotFoundError
        If CONFIGS_DIR/{config_name}.yml does not exist.
    yaml.YAMLError
        If the file is not valid YAML.
    TypeError
        If the YAML root is not a mapping.
    """
    config_path = Path(os.environ.get("CONFIGS_DIR")) / f"{config_name}.yml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    # The YAML root must be a mapping; bail out without returning a partial
    # config object if it is a sequence, scalar, or empty document.
    if not isinstance(data, dict):
        raise TypeError(
            f"Config file {config_path} root must be a YAML mapping, "
            f"got {type(data).__name__}"
        )

    config = SimpleNamespace(**data)

    # Convert top-level scalar path-like strings to Path objects. Nested
    # list/dict members (e.g. NSLC strings) are intentionally left untouched.
    for key, value in vars(config).items():
        if isinstance(value, str) and looks_like_path(value):
            setattr(config, key, Path(value))

    # Evaluate simple arithmetic expressions (e.g. "280*2.5") for eligible keys
    math_eligible_keys = {"value", "duration"}
    for key in math_eligible_keys:
        if hasattr(config, key):
            setattr(config, key, _evaluate_math_expr(getattr(config, key)))

    # Apply waveform defaults for seismo-acoustic alarm types
    if config.alarm_type in ("RSAM", "Infrasound", "Tremor"):
        if not hasattr(config, "taper") or config.taper is None:
            config.taper = 5
        if not hasattr(config, "latency") or config.latency is None:
            config.latency = 10

    if config.alarm_type == "Infrasound":
        config = update_infrasound_config(config)
        if not hasattr(config, "duration") or config.duration is None:
            config.duration = os.environ.get("INFRASOUND_DURATION", 90)
            
    if config.alarm_type == "RSAM":
        if not hasattr(config, "duration") or config.duration is None:
            config.duration = os.environ.get("RSAM_DURATION", 300)

    if config.alarm_type == "Tremor":
        if not hasattr(config, "grid_file"):
            config.grid_file = TMP_DIR / f"{config.alarm_name.replace(' ', '_')}_grid.npz"
        if not hasattr(config, "lookback_window") or config.lookback_window is None:
            config.lookback_window = int(os.environ.get("TREMOR_LOOKBACK_WINDOW", 60))
        if not hasattr(config, "window_length") or config.window_length is None:
            config.window_length = os.environ.get("TREMOR_WINDOW_LENGTH", 300)

    return config


def update_infrasound_config(config):
    """
    Enrich Infrasound targets with location and velocity defaults.

    For each entry in ``config.targets`` (the canonical lowercase key), fill
    ``lat``/``lon`` from the Volcano_List row matching the target ``name`` when
    either is absent, and default ``vmin``/``vmax``/``cmin`` from the
    ``INFRASOUND_VMIN``/``INFRASOUND_VMAX`` environment variables (0.28/0.45)
    when absent. Pre-existing ``lat``/``lon``/``vmin``/``vmax`` values are
    preserved.

    Parameters
    ----------
    config : types.SimpleNamespace
        Parsed Infrasound config exposing ``targets`` as a list of dicts.

    Returns
    -------
    types.SimpleNamespace
        The same Config_Object with each target enriched in place.

    Raises
    ------
    ValueError
        If a target lacks explicit ``lat``/``lon`` and its ``name`` is not
        found in the Volcano_List (Req 14.4).
    """
    df = load_volcano_list()
    VMIN = os.environ.get("INFRASOUND_VMIN", 0.28)
    VMAX = os.environ.get("INFRASOUND_VMAX", 0.45)
    CMIN = os.environ.get("INFRASOUND_CMIN", 0.6)
    PLOT_DURATION = os.environ.get("INFRASOUND_PLOT_DURATION", 3600)

    # --- Infrasound defaults ---
    if not hasattr(config, "min_channels"):
        config.min_channels = os.environ.get("INFRASOUND_MIN_CHANNELS", 3)
    if not hasattr(config, "window_length"):
        config.lts_window_length = os.environ.get("LTS_WINDOW_LENGTH", 30)
    if not hasattr(config, "overlap"):
        config.lts_overlap = os.environ.get("LTS_OVERLAP", 15)
    if not hasattr(config, "lts_alpha"):
        config.lts_alpha = os.environ.get("LTS_ALPHA", 0.5)
    if not hasattr(config, "lts_n_samples"):
        config.lts_n_samples = int(os.environ.get("LTS_N_SAMPLES", 100))
    if not hasattr(config, "max_gap_fraction"):
        config.max_gap_fraction = os.environ.get("MAX_GAP_FRACTION", 0.5)

    for i, target in enumerate(config.targets):
        if "lat" not in target or "lon" not in target:
            v_name = target["name"]
            matches = df[df["Name"] == v_name]
            if matches.empty:
                raise ValueError(
                    f"Infrasound target '{v_name}' not found in the volcano "
                    f"list and no explicit lat/lon provided; cannot enrich "
                    f"target coordinates."
                )
            v_row = matches.squeeze()
            tmp_dict = {
                "name": v_row["Name"],
                "lon": v_row.Longitude.item(),
                "lat": v_row.Latitude.item(),
            }
            config.targets[i].update(tmp_dict)
        if "vmin" not in target:
            config.targets[i].update({"vmin": VMIN})
        if "vmax" not in target:
            config.targets[i].update({"vmax": VMAX})
        if "cmin" not in target:
            config.targets[i].update({"cmin": CMIN})
        if "plot_duration" not in target:
            config.targets[i]["plot_duration"] = float(PLOT_DURATION)
        else:
            config.targets[i]["plot_duration"] = float(
                _evaluate_math_expr(target["plot_duration"])
            )

    return config


def load_volcano_list(volcano_file=None):
    """
    Load volcano list from file, supporting .xlsx, .csv, or .txt formats.
    
    Requires the following columns: "Name", "Latitude", "Longitude".
    Additional columns are preserved if present.

    Parameters
    ----------
    volcano_file : str, Path, or None
        Path to the volcano list file (.xlsx, .csv, or .txt). If None (default),
        loads from VOLCANO_LIST environment variable. If that is also unset,
        falls back to the bundled volcano_list.xlsx in volc_alarms.data.

    Returns
    -------
    pd.DataFrame
        DataFrame with required columns: Name, Latitude, Longitude
        
    Raises
    ------
    ValueError
        If file format is not supported or required columns are missing
    """
    if volcano_file is None:
        volcano_file = os.environ.get("VOLCANO_LIST")
        if volcano_file is None:
            # Fallback if load_environment() hasn't been called yet
            from importlib.resources import files
            volcano_file = files("volc_alarms.data").joinpath("volcano_list.csv")
    
    volcano_file = Path(volcano_file)
    
    required_columns = {"Name", "Latitude", "Longitude"}
    
    if volcano_file.suffix.lower() == ".xlsx":
        df = pd.read_excel(volcano_file)
    elif volcano_file.suffix.lower() == ".csv":
        df = pd.read_csv(volcano_file)
    elif volcano_file.suffix.lower() == ".txt":
        # Try to infer delimiter for .txt files
        df = pd.read_csv(volcano_file, sep=None, engine="python")
    else:
        raise ValueError(
            f"Unsupported file format: {volcano_file.suffix}. "
            "Must be .xlsx, .csv, or .txt"
        )
    
    # Check for required columns (case-insensitive)
    df_cols_lower = {col.lower(): col for col in df.columns}
    missing_cols = []
    
    for req_col in required_columns:
        if req_col.lower() not in df_cols_lower:
            missing_cols.append(req_col)
    
    if missing_cols:
        raise ValueError(
            f"Missing required columns: {missing_cols}. "
            f"File has columns: {list(df.columns)}"
        )
    
    # Rename columns to match expected case (preserve other columns as-is)
    rename_dict = {}
    for req_col in required_columns:
        if req_col.lower() in df_cols_lower and req_col not in df.columns:
            rename_dict[df_cols_lower[req_col.lower()]] = req_col
    
    if rename_dict:
        df = df.rename(columns=rename_dict)
    
    return df


def setup_root_logger(
    log_dir=None,
    config_name=None,
    log_level=logging.INFO,
):
    """
    Configure the root logger with appropriate handler.

    This should be called once from the main script (run_alarm.py) to set up
    the root logger with either a file handler (when FROMCRON) or console handler.
    All module loggers will propagate to this root logger.

    Parameters
    ----------
    log_dir : str, optional
        Directory for log files (required if running from cron).
        If None during cron mode, attempts to read from LOGS_DIR environment variable.
    config_name : str, optional
        Name of the alarm configuration (used in log filename).
        Required when running from cron.
    log_level : int, optional
        Logging level (default: logging.INFO).

    Returns
    -------
    logging.Logger
        Configured root logger instance.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers to avoid duplicates
    if root_logger.handlers:
        root_logger.handlers.clear()

    # Format string with millisecond precision
    format_string = "%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Create formatter
    formatter = logging.Formatter(format_string, datefmt=date_format)

    # Redirect stderr to logger to capture C/FORTRAN library output
    # (e.g., earthworm client messages)
    stderr_logger = logging.getLogger("stderr")
    sys.stderr = StderrToLogger(stderr_logger, log_level=logging.WARNING)

    # Check if running from cron
    from_cron = os.environ.get("FROMCRON", "").lower() == "yep"

    if from_cron:
        # Setup file handler
        if log_dir is None:
            log_dir = os.environ.get("LOGS_DIR")
            if not log_dir:
                raise ValueError(
                    "log_dir must be provided or LOGS_DIR environment variable must be set"
                )

        if config_name is None:
            raise ValueError("config_name must be provided when running from cron")

        # Create log directory if it doesn't exist
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename with current time rounded to nearest interval
        log_hour_interval = int(os.environ.get("LOG_HOUR_INTERVAL", 12))
        current_time = time.localtime()
        hour = current_time.tm_hour
        rounded_hour = (hour // log_hour_interval) * log_hour_interval
        current_time_str = f"{time.strftime('%Y%m%d', current_time)}-{rounded_hour:02d}"
        log_file = os.path.join(log_dir, f"{config_name}-{current_time_str}.log")

        # Clean up old log files beyond retention period
        log_days_keep = int(os.environ.get("LOG_DAYS_KEEP", 7))
        cutoff = time.time() - (log_days_keep * 86400)
        for old_log in glob.glob(os.path.join(log_dir, f"{config_name}-*.log")):
            if os.path.getmtime(old_log) < cutoff:
                os.remove(old_log)

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        # Interactive mode: log to console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name):
    """
    Get or create a module logger.

    Returns a logger with the given name that propagates to the root logger.
    Module-level loggers should call this function to get their logger instance.
    The root logger will be configured separately (e.g., by run_alarm.py).

    Parameters
    ----------
    name : str
        Logger name (typically __name__).

    Returns
    -------
    logging.Logger
        Configured logger instance that propagates to root.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


class LockFile:
    """
    Context manager for file-based locking.
    
    Prevents multiple instances of the same alarm from running simultaneously
    by using a lock file directory. The lock file contains the PID of the
    running process.
    """
    def __init__(self, lock_dir, config_name, timeout=300):
        """
        Initialize the lock file manager.
        
        Parameters
        ----------
        lock_dir : str
            Directory where lock files are stored.
        config_name : str
            Name of the configuration (used in lock filename).
        timeout : int, optional
            Seconds to wait before considering a lock stale (default: 300).
        """
        self.lock_dir = Path(lock_dir)
        self.config_name = config_name
        self.timeout = timeout
        self.lock_file = self.lock_dir / f"{config_name}.lock"
        self.acquired = False

    def __enter__(self):
        """Acquire the lock."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock."""
        self.release()

    def acquire(self):
        """
        Acquire the lock, blocking if necessary.
        
        Raises
        ------
        RuntimeError
            If the lock cannot be acquired (another instance is running).
        """
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if lock file exists
        if self.lock_file.exists():
            try:
                with open(self.lock_file, 'r') as f:
                    old_pid = int(f.read().strip())
            except (ValueError, IOError):
                # Lock file is corrupted, remove it
                self.lock_file.unlink()
                old_pid = None
            
            if old_pid is not None:
                # Check if the process is still running
                try:
                    os.kill(old_pid, 0)  # Signal 0 doesn't kill, just checks if process exists
                    raise RuntimeError(
                        f"Configuration '{self.config_name}' is already running (PID: {old_pid})"
                    )
                except ProcessLookupError:
                    # Process is not running, remove stale lock
                    self.lock_file.unlink()
        
        # Write current PID to lock file
        with open(self.lock_file, 'w') as f:
            f.write(str(os.getpid()))
        
        self.acquired = True

    def release(self):
        """Release the lock."""
        if self.acquired and self.lock_file.exists():
            try:
                with open(self.lock_file, 'r') as f:
                    lock_pid = int(f.read().strip())
                # Only remove if it's our lock
                if lock_pid == os.getpid():
                    self.lock_file.unlink()
            except (ValueError, IOError):
                pass
            self.acquired = False
