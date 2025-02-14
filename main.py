#!/home/rtem/.conda/envs/alarms/bin/python
# -*- coding: utf-8 -*-

# alarm_codes is a directory
# utils is file. Importing it allows for error email delivery & importing environment variables
import time
start = time.time()

import argparse
from importlib import import_module
from alarm_codes import utils
from obspy import UTCDateTime as utc
import os
import sys
import traceback

parser = argparse.ArgumentParser(epilog="e.g.: python main.py Pavlof_RSAM 201701020205")
parser.add_argument("config", type=str, help="Name of the config file")
parser.add_argument("-t", "--time", type=str, help=f"utc time stamp fmt:YYYYMMDDHHMM\n(optional, otherwise grabs current utc time)")
parser.add_argument("--test", help="Run in test mode", action="store_true")
args = parser.parse_args()


# if run from a cron, write output to 4-hourly file in the logs directory
if os.getenv("FROMCRON") == "yep":
    T0 = utc.now()
    d_hour = int(T0.strftime("%H")) % 4
    f_time = (
        utc(T0.strftime("%Y%m%d")) + (int(T0.strftime("%H")) - d_hour) * 3600
    )
    file = (
        os.environ["LOGS_DIR"]
        + "/"
        + sys.argv[1]
        + "-"
        + f_time.strftime("%Y%m%d-%H")
        + ".out"
    )
    os.system(f"touch {file}")
    f = open(file, "a")
    sys.stdout = sys.stderr = f

    # keep .keep file from getting pruned by other cron deleting old log-files
    keep_file = os.environ["LOGS_DIR"] + "/.keep"
    os.system(f"touch {keep_file}")

print("\n-----------------------------------------")


# no time given, use current time
if args.time is None:
    T0 = utc.utcnow() # get current timestamp
    T0 = utc(T0.strftime("%Y-%m-%d %H:%M")) # round down to the nearest minute
else:
    T0 = utc(args.time)

try:
    # import the config file for the alarm you're running
    config = import_module(f"alarm_configs.{args.config}_config")
    ALARM = import_module(f"alarm_codes.{config.alarm_type}")
    if args.test:
        print("Running alarm in test mode")
    ALARM.run_alarm(config, T0, test=args.test)
# if error, send message to designated recipients
except:
    print("Error...")
    b = traceback.format_exc()
    message = "".join("{}\n".format(a) for a in b.splitlines())
    message = "{}\n\n{}".format(T0.strftime("%Y-%m-%d %H:%M"), message)
    subject = config.alarm_name + " error"
    attachment = "alarm_aux_files/oops.jpg"
    utils.send_alert("Error", subject, message, attachment)

print(utc.utcnow().strftime("%Y.%m.%d %H:%M:%S"))
end = time.time()
print(f"[{end - start:.2f} seconds to complete alarm]")
print("-----------------------------------------\n")


if os.getenv("FROMCRON") == "yep":
    f.close()

sys.exit()