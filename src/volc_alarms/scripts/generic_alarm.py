import argparse
import os
from pathlib import Path

from volc_alarms.utils.messaging import icinga
from volc_alarms.utils.setup_utils import (
    get_logger,
    load_environment,
    setup_root_logger,
    LockFile,
)


def config():
    return


def parse_args():
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
