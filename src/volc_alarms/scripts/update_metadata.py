"""Command-line entry point for refreshing station metadata.

Downloads up-to-date StationXML for all channels used by the seismic alarms
and writes it to ``STATION_XML`` via
:func:`volc_alarms.utils.downloading.download_station_xml`. Exposed as the
``update-metadata`` console script.
"""

import argparse
import os
import time
from pathlib import Path

from volc_alarms.utils.downloading import download_station_xml
from volc_alarms.utils.setup_utils import (
    LockFile,
    get_logger,
    load_environment,
    setup_root_logger,
)


def parse_args():
    """Parse command-line arguments for the metadata update tool.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        env_file : str or None
            Path to a ``.env`` file; if omitted, the directory tree is
            searched upward.
    """
    parser = argparse.ArgumentParser(prog="update-metadata")
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
    return parser.parse_args()


def main():
    """Refresh the local StationXML metadata from the command line.

    Loads the environment, configures logging, and acquires a single-instance
    lock, then rebuilds the StationXML file via
    :func:`volc_alarms.utils.downloading.download_station_xml`. The lock is
    always released on exit.

    Notes
    -----
    Intended to be invoked via the ``update-metadata`` console script. Reads
    arguments from the command line and takes no parameters.
    """
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
