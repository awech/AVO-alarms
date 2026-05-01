import os
import time

from dotenv import load_dotenv

from avo_alarms.utils.downloading import download_station_xml
from avo_alarms.utils.setup_utils import get_logger, setup_root_logger

load_dotenv()

def main():

    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")
    else:
        setup_root_logger()

    logger = get_logger(__name__)
    logger.info(f"Begin metadata update")

    start = time.time()
    download_station_xml()

    sep_string = "\n-----------------------------------------\n"
    sep_string+= "\n-----------------------------------------"
    logger.info(f"[{time.time() - start:.2f} seconds to complete update]{sep_string}")

if __name__ == "__main__":
    main()
