"""Command-line entry point for resetting a generic alarm's Icinga status.

Sets an arbitrary named alarm service to an empty ``OK`` state in Icinga.
Useful for alarm services that have no detection logic of their own but still
need a periodic heartbeat. Exposed as the ``generic-alarm`` console script.
"""

import argparse
import os
from pathlib import Path

from volc_alarms.utils.messaging import icinga
from volc_alarms.utils.setup_utils import (
    LockFile,
    get_logger,
    load_environment,
    setup_root_logger,
)


def config():
    """Lightweight namespace carrier for the generic alarm's settings.

    This empty function is used as a mutable attribute holder: ``main`` sets
    ``config.alarm_name`` and ``config.icinga_service_name`` on it and passes
    it to :func:`volc_alarms.utils.messaging.icinga`, which only reads those
    attributes.

    Returns
    -------
    None
    """
    return


def parse_args():
    """Parse command-line arguments for the generic alarm tool.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        alarm : str
            Alarm name, with ``_`` standing in for spaces.
        env_file : str or None
            Path to a ``.env`` file; if omitted, the directory tree is
            searched upward.
    """
    parser = argparse.ArgumentParser(prog="generic-alarm")
    parser.add_argument(
        "alarm",
        type=str,
        help="Alarm name. Use '_' in place of spaces.",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
    return parser.parse_args()


def main():
    """Set a named alarm service to an empty OK state in Icinga.

    Loads the environment, configures logging, acquires a single-instance
    lock keyed on the alarm name, and sends an ``OK`` heartbeat with an empty
    state message to Icinga. The lock is always released on exit.

    Notes
    -----
    Intended to be invoked via the ``generic-alarm`` console script. Reads
    arguments from the command line and takes no parameters.
    """
    args = parse_args()
    load_environment(args.env_file)

    alarm_name = args.alarm.replace("_", " ")
    config.icinga_service_name = alarm_name
    config.alarm_name = alarm_name

    # Log and set lock directory based on cron status
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name=alarm_name)
        lock_dir = os.getenv("LOCK_DIR", os.getenv("LOGS_DIR"))
    else:
        setup_root_logger()
        lock_dir = Path.home() / ".tmp" / "alarms"

    logger = get_logger(__name__)
    logger.info(f"Setting {config.alarm_name} icinga status to OK and empty.")

    try:
        lock = LockFile(lock_dir, alarm_name.replace(" ", "_"))
        lock.acquire()
    except RuntimeError as e:
        logger.warning(str(e))
        return

    try:
        state = "OK"
        state_message = "Empty alarm service"

        icinga(config, state, state_message)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
