import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from obspy import UTCDateTime

from ..utils.processing import update_stationXML
from ..utils.setup_utils import setup_root_logger

load_dotenv()

def main():

    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")
    else:
        setup_root_logger()

    update_stationXML()


if __name__ == "__main__":
    main()
