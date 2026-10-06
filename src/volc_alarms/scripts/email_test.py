"""Command-line entry point for sending a test alert email.

Sends a single test email (with the bundled ``oops.jpg`` attachment) to the
test recipients, verifying that SMTP configuration and distribution lists are
working. Exposed as the ``email-test`` console script.
"""

import argparse
import os
import socket
from importlib.resources import files
from pathlib import Path

from obspy import UTCDateTime

from volc_alarms.utils.messaging import send_alert
from volc_alarms.utils.setup_utils import (
    LockFile,
    get_logger,
    load_environment,
    setup_root_logger,
)


def parse_args():
    """Parse command-line arguments for the email test tool.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        env_file : str or None
            Path to a ``.env`` file; if omitted, the directory tree is
            searched upward.
    """

    parser = argparse.ArgumentParser(prog="email-test")
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
    return parser.parse_args()


def main():
    """Send a single test alert email from the command line.

    Loads the environment, configures logging, acquires a single-instance
    lock, and sends a short test message (with the bundled ``oops.jpg``
    attachment) to the test recipients. The lock is always released on exit.

    Notes
    -----
    Intended to be invoked via the ``email-test`` console script. Reads
    arguments from the command line and takes no parameters.
    """
    args = parse_args()
    load_environment(args.env_file)

    # Log and set lock directory based on cron status
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Email_test")
        lock_dir = os.getenv("LOCK_DIR", os.getenv("LOGS_DIR"))
    else:
        setup_root_logger()
        lock_dir = Path.home() / ".tmp" / "alarms"

    logger = get_logger(__name__)
    logger.info("Sending email test alert")

    try:
        lock = LockFile(lock_dir, "Email_test")
        lock.acquire()
    except RuntimeError as e:
        logger.warning(str(e))
        return

    try:
        T0 = UTCDateTime.now() - 3600 * 9
        hostname = socket.gethostname()
        message = f"{T0.strftime('%Y-%m-%d %H:%M')} from {hostname} user {os.environ.get('LOGNAME')}"
        subject = "Alarm Email Test"

        attachment = files("volc_alarms.data").joinpath("oops.jpg")
        send_alert("Test", subject, message, attachment)
        logger.info("Finished")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
