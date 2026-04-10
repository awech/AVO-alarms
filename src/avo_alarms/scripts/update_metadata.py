import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from obspy import UTCDateTime

from ..utils.processing import update_stationXML
from ..utils.logging_config import get_logger

load_dotenv()

def main():
    logger = get_logger(__name__)
    
    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        logger = get_logger(__name__, log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")

    update_stationXML()


if __name__ == "__main__":
    main()
