import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from obspy import UTCDateTime

from ..utils.processing import update_stationXML

load_dotenv()

def main():
    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        file = Path(os.environ["LOGS_DIR"]) / f"Metadata-{UTCDateTime.now().strftime('%Y%m%d')}.log"
        os.system("touch {}".format(file))
        f = open(file, "a")
        sys.stdout = sys.stderr = f

    update_stationXML()


if __name__ == "__main__":
    main()
