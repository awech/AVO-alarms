import os
import sys
from obspy import UTCDateTime
from pathlib import Path

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils.processing import update_stationXML


def update_metadata():
    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        file = (
            os.environ["LOGS_DIR"]
            + "/Metadata-"
            + UTCDateTime.now().strftime("%Y%m%d")
            + ".log"
        )
        os.system("touch {}".format(file))
        f = open(file, "a")
        sys.stdout = sys.stderr = f

    update_stationXML()


if __name__ == "__main__":
    update_metadata()
