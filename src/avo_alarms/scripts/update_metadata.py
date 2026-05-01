import os

from dotenv import load_dotenv

from avo_alarms.utils.downloading import download_station_xml
from avo_alarms.utils.setup_utils import setup_root_logger

load_dotenv()

def main():

    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Metadata")
    else:
        setup_root_logger()

    download_station_xml()


if __name__ == "__main__":
    main()
