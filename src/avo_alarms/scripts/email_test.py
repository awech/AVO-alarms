import os
import socket
import sys
from pathlib import Path

from obspy import UTCDateTime

from ..utils.messaging import send_alert


def main():
    if os.getenv("FROMCRON") == "yep":
        file = (
            os.environ["LOGS_DIR"]
            + "/Email_test-"
            + UTCDateTime.now().strftime("%Y%m%d")
            + ".log"
        )
        os.system("touch {}".format(file))
        f = open(file, "a")
        sys.stdout = sys.stderr = f

    T0 = UTCDateTime.now() - 3600 * 9
    hostname = socket.gethostname()
    message = f"{T0.strftime('%Y-%m-%d %H:%M')} from {hostname} user {os.environ.get('LOGNAME')}"
    subject = "Alarm Email Test"

    attachment = Path(os.environ["HOME_DIR"]) / "alarm_aux_files" / "oops.jpg"
    send_alert("Error", subject, message, attachment)
    print("Finished")


if __name__ == "__main__":
    main()
