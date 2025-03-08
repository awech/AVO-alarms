import os
import sys
from obspy import UTCDateTime
from pathlib import Path

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils.messaging import send_alert


def send_test_email():
    if os.getenv("FROMCRON") == "yep":
        file = (
            os.environ["LOGS_DIR"]
            + "/Email_test-"
            + UTCDateTime.now().strftime("%Y%m%d-%H")
            + ".out"
        )
        os.system("touch {}".format(file))
        f = open(file, "a")
        sys.stdout = sys.stderr = f

    T0 = UTCDateTime.now() - 3600 * 8
    message = f"{T0.strftime('%Y-%m-%d %H:%M')} from avoalarm2"
    subject = "Alarm Email Test"

    attachment = current_path.parents[0] / "alarm_aux_files" / "oops.jpg"
    send_alert("Error", subject, message, attachment)
    print("Finished")


if __name__ == "__main__":
    send_test_email()
