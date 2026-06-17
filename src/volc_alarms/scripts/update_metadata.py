import argparse
import os
import time
from pathlib import Path

from volc_alarms.utils.downloading import download_station_xml
from volc_alarms.utils.setup_utils import (
    get_logger,
    load_environment,
    setup_root_logger,
    LockFile,
)


def parse_args():
    parser = argparse.ArgumentParser(prog="update-metadata")
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

    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")
    else:
        setup_root_logger()

    # Log and set lock directory based on cron status
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")
        lock_dir = os.getenv("LOCK_DIR", os.getenv("LOGS_DIR"))
    else:
        setup_root_logger()
        lock_dir = Path.home() / ".tmp" / "alarms"

    logger = get_logger(__name__)

    try:
        lock = LockFile(lock_dir, "Metadata")
        lock.acquire()
    except RuntimeError as e:
        logger.warning(str(e))
        return

    try:
        logger.info("Begin metadata update")
        start = time.time()
        download_station_xml()

        sep_string = "\n-----------------------------------------\n"
        sep_string+= "\n-----------------------------------------"
        logger.info(f"[{time.time() - start:.2f} seconds to complete update]{sep_string}")
    finally:
        lock.release()

if __name__ == "__main__":
    main()
