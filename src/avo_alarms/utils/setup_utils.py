"""
Centralized logging configuration for AVO Alarms package.

Provides setup functions to configure loggers with appropriate handlers
based on whether the code is running from cron or interactively.

When FROMCRON environment variable is set, logs are written to rotating
files (4-hour intervals, 2-week retention). Otherwise, logs go to console.
"""

import importlib.util
import io
import logging
import logging.handlers
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
from obspy import UTCDateTime as utc


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


# TODO consider adding function that reads config and .env and sets all defaults


def load_config(config_name):
    """
    Load configuration from a Python file in CONFIGS_DIR.

    Loads a Python module from CONFIGS_DIR/{config_name}.py and converts
    any string attributes that look like file paths to pathlib.Path objects.

    Parameters
    ----------
    config_name : str
        Name of the config file (without .py extension)

    Returns
    -------
    module
        The loaded config module with path strings converted to Path objects
    """
    config_path = Path(os.environ.get("CONFIGS_DIR")) / f"{config_name}.py"
    spec = importlib.util.spec_from_file_location(config_name, config_path)
    config = importlib.util.module_from_spec(spec)
    sys.modules[config_name] = config
    spec.loader.exec_module(config)
    
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
    
    # Iterate through config attributes and convert path-like strings to Path objects
    for attr_name in dir(config):
        # Skip private/magic attributes and imported modules
        if attr_name.startswith('_'):
            continue
        
        try:
            attr_value = getattr(config, attr_name)
            # Only process strings (skip callables, modules, etc.)
            if isinstance(attr_value, str) and looks_like_path(attr_value):
                setattr(config, attr_name, Path(attr_value))
        except (TypeError, AttributeError):
            # Some attributes might not be settable or might cause issues
            continue
    
    return config


def load_volcano_list(volcano_file=None):
    """
    Load volcano list from file, supporting .xlsx, .csv, or .txt formats.
    
    Requires the following columns: "Volcano", "Latitude", "Longitude".
    Additional columns are preserved if present.

    Parameters
    ----------
    volcano_file : str, Path, or None
        Path to the volcano list file (.xlsx, .csv, or .txt). If None (default),
        loads from VOLCANO_LIST environment variable.

    Returns
    -------
    pd.DataFrame
        DataFrame with required columns: Volcano, Latitude, Longitude
        
    Raises
    ------
    ValueError
        If file format is not supported or required columns are missing
    """
    if volcano_file is None:
        volcano_file = os.environ.get("VOLCANO_LIST")
        if volcano_file is None:
            raise ValueError(
                "VOLCANO_LIST environment variable not set and no volcano_file provided"
            )
    
    volcano_file = Path(volcano_file)
    
    required_columns = {"Volcano", "Latitude", "Longitude"}
    
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


def update_arguments(args):

    if args.test and args.mm is None:
        args.mm = False
    if args.test and args.icinga is None:
        args.icinga = False

    if args.mm is None:
        args.mm = True
    if args.icinga is None:
        args.icinga = True

    if args.time is None:
        T0 = utc.utcnow()  # no time given, use current timestamp
        args.time = utc(T0.strftime("%Y-%m-%d %H:%M"))  # round down to the nearest minute
    else:
        args.time = utc(args.time)

    return args


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
        # Setup file handler with timed rotation
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

        # Generate filename with current time rounded to nearest 4-hour mark
        # Time format: YYYYMMDD-HH where HH is 00, 04, 08, 12, 16, or 20
        current_time = time.localtime()
        hour = current_time.tm_hour
        rounded_hour = (hour // 4) * 4
        current_time_str = f"{time.strftime('%Y%m%d', current_time)}-{rounded_hour:02d}"
        log_file = os.path.join(log_dir, f"{config_name}-{current_time_str}.log")

        # TimedRotatingFileHandler
        # when='H', interval=4 -> rotate every 4 hours
        # backupCount=84 -> keep 84 rotations = 14 days (84 / 6 rotations per day)
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when="H",
            interval=4,
            backupCount=84,
            encoding="utf-8",
        )

        # Custom namer: when file rotates, rename with timestamp rounded to 4-hour mark
        def namer(default_name):
            # Rotate timestamp rounded to nearest 4-hour mark (00, 04, 08, 12, 16, 20)
            rotation_time = time.localtime()
            rotation_hour = rotation_time.tm_hour
            rounded_hour = (rotation_hour // 4) * 4
            rotation_time_str = f"{time.strftime('%Y%m%d', rotation_time)}-{rounded_hour:02d}"
            return os.path.join(log_dir, f"{config_name}-{rotation_time_str}.log")

        handler.namer = namer

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
