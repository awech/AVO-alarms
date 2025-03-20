#!/home/rtem/.conda/envs/alarms/bin/python
# -*- coding: utf-8 -*-

import time
start = time.time()

import argparse
from importlib import import_module
from utils import messaging
from obspy import UTCDateTime as utc
import os
import sys
import traceback
from pathlib import Path

parser = argparse.ArgumentParser(epilog="e.g.: python main.py Pavlof_RSAM 201701020205")
parser.add_argument("config", type=str, help="Name of the config file")
parser.add_argument("-t", "--time", type=str, 
                    help="utc time stamp:YYYYMMDDHHMM (optional, otherwise grabs current utc time)")
parser.add_argument("--test", help="Run in test mode", action="store_true")
parser.add_argument("--mm", help="Post to mattermost", action=argparse.BooleanOptionalAction, default=None)
parser.add_argument("--icinga", help="Send hearbeat to icinga", action=argparse.BooleanOptionalAction, default=None)
args = parser.parse_args()

if args.test and args.mm is None:
    args.mm = False
if args.test and args.icinga is None:
    args.icinga = False

if args.mm is None:
    args.mm = True
if args.icinga is None:
    args.icinga = True

if args.test:
    print("Running alarm in test mode")

if os.getenv("FROMCRON") == "yep":
    # if run from a cron, write output to 4-hourly file in the logs directory
    T0 = utc.now()
    d_hour = int(T0.strftime("%H")) % 4
    f_time = utc(T0.strftime("%Y%m%d")) + (int(T0.strftime("%H")) - d_hour) * 3600
    file = Path(os.environ["LOGS_DIR"]) / f"{args.config}-{f_time.strftime('%Y%m%d-%H')}.out"
    os.system(f"touch {file}")
    f = open(file, "a")
    sys.stdout = sys.stderr = f

    # keep .keep file from getting pruned by other cron deleting old log-files
    keep_file = Path(os.environ["LOGS_DIR"]) / ".keep"
    os.system(f"touch {keep_file}")

print("\n-----------------------------------------")


if args.time is None:
    T0 = utc.utcnow()  # no time given, use current timestamp
    T0 = utc(T0.strftime("%Y-%m-%d %H:%M"))  # round down to the nearest minute
else:
    T0 = utc(args.time)

try:
    # import the config file for the alarm you're running
    config = import_module(f"alarm_configs.{args.config}_config")
    ALARM = import_module(f"alarm_codes.{config.alarm_type}")
    ALARM.run_alarm(config, T0, test_flag=args.test, mm_flag=args.mm, icinga_flag=args.icinga)
except:
    # if error, send message to designated recipients
    print("Error...")
    b = traceback.format_exc()
    message = "".join(f"{a}\n" for a in b.splitlines())
    message = f"{str(T0)}\n\n{message}"
    subject = config.alarm_name + " error"
    filename = Path("alarm_aux_files") / "oops.jpg"
    messaging.send_alert("Error", subject, message, attachment=filename)

print(utc.utcnow().strftime("%Y.%m.%d %H:%M:%S"))
end = time.time()
print(f"[{end - start:.2f} seconds to complete alarm]")
print("-----------------------------------------\n")


if os.getenv("FROMCRON") == "yep":
    f.close()

sys.exit()