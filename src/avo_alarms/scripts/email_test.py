import argparse
import os
import socket
from pathlib import Path

from obspy import UTCDateTime

from avo_alarms.utils.messaging import send_alert
from avo_alarms.utils.setup_utils import (
    get_logger,
    load_environment,
    setup_root_logger,
    LockFile,
)


def parse_args():
    parser = argparse.ArgumentParser(prog="email-test")
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
    return parser.parse_args()


def main():

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

        attachment = Path(os.environ["HOME_DIR"]) / "alarm_aux_files" / "oops.jpg"
        send_alert("Error", subject, message, attachment)
        logger.info("Finished")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
