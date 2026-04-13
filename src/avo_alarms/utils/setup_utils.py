"""
Centralized logging configuration for AVO Alarms package.

Provides setup functions to configure loggers with appropriate handlers
based on whether the code is running from cron or interactively.

When FROMCRON environment variable is set, logs are written to rotating
files (4-hour intervals, 2-week retention). Otherwise, logs go to console.
"""

import importlib.util
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

from obspy import UTCDateTime as utc


def load_config(config_name):
    """
    Load logging configuration from environment variables.

    This function can be extended in the future to load more complex configurations
    from a file or other source if needed. For now, it simply reads the relevant
    environment variables and returns them in a dictionary.

    Returns
    -------
    dict
        Dictionary containing logging configuration parameters.
    """
    config = {
        "log_dir": os.environ.get("LOGS_DIR"),
        "config_name": os.environ.get("CONFIG_NAME"),
        "log_level": logging.INFO,
    }

    config_path = Path(os.environ.get("CONFIGS_DIR")) / f"{config_name}.py"
    spec = importlib.util.spec_from_file_location(config_name, config_path)
    config = importlib.util.module_from_spec(spec)
    sys.modules[config_name] = config
    spec.loader.exec_module(config)
    
    return config


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
