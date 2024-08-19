#!/home/rtem/.conda/envs/alarms/bin/python
import os
import sys
from obspy import UTCDateTime

import sys

sys.path.append("/alarms")
from alarm_codes import utils

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

# message = "Body"
T0 = UTCDateTime.now() - 3600 * 8
message = f"{T0.strftime('%Y-%m-%d %H:%M')}"
print(message)
subject = "Alarm Email Test"
attachment = os.environ["HOME_DIR"] + "/alarm_aux_files/oops.jpg"

utils.send_alert("Error", subject, message, attachment)
print("Finished")
