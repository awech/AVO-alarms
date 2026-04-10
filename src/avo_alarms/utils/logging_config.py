"""
Centralized logging configuration for AVO Alarms package.

Provides setup functions to configure loggers with appropriate handlers
based on whether the code is running from cron or interactively.

When FROMCRON environment variable is set, logs are written to rotating
files (4-hour intervals, 2-week retention). Otherwise, logs go to console.
"""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(
    name,
    log_dir=None,
    config_name=None,
    log_level=logging.INFO,
):
    """
    Configure and return a logger with appropriate handlers.

    Parameters
    ----------
    name : str
        Logger name (typically module name or script name).
    log_dir : str, optional
        Directory for log files (required if running from cron).
        If None, will attempt to read from LOGS_DIR environment variable.
    config_name : str, optional
        Name of the alarm configuration (used in log filename).
        If None, uses the logger name.
    log_level : int, optional
        Logging level (default: logging.INFO).

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

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

        # Create log directory if it doesn't exist
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Use config_name in filename if provided, otherwise use logger name
        filename = config_name or name.replace(".", "_")
        log_file = os.path.join(log_dir, f"{filename}-%(date)s.log")

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

        # Use strftime for date format in filename
        handler.namer = lambda name: name.replace("%(date)s", time.strftime("%Y%m%d-%H"))

        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        # Setup console handler for interactive mode
        handler = logging.StreamHandler()
        handler.setLevel(log_level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger(name, log_dir=None, config_name=None):
    """
    Get or create a logger with standard configuration.

    Convenience function that calls setup_logger with default parameters.

    Parameters
    ----------
    name : str
        Logger name.
    log_dir : str, optional
        Directory for log files (when running from cron).
    config_name : str, optional
        Configuration name for log filename.

    Returns
    -------
    logging.Logger
        Configured logger instance.
    """
    return setup_logger(name, log_dir=log_dir, config_name=config_name)
