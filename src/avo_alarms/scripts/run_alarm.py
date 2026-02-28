"""Command-line entry point for running volcano monitoring alarms."""

import argparse
import importlib.util
import os
import sys
import time
import traceback
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv
from obspy import UTCDateTime as utc

from ..utils import messaging


def main():
    """Main entry point for the alarm runner."""
    
    start = time.time()
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        prog="run-alarm",
        epilog="e.g.: run-alarm Pavlof_RSAM --test or run-alarm Pavlof_RSAM 201701020205"
    )
    parser.add_argument("config", type=str, help="Name of the config file")
    parser.add_argument(
        "-t", "--time", type=str,
        help="utc time stamp:YYYYMMDDHHMM (optional, otherwise grabs current utc time)"
    )
    parser.add_argument("--test", help="Run in test mode", action="store_true")
    parser.add_argument(
        "--mm", help="Post to mattermost",
        action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument(
        "--icinga", help="Send heartbeat to icinga",
        action=argparse.BooleanOptionalAction, default=None
    )
    args = parser.parse_args()

    # TODO: add "force trigger" (or similar) argument to force an alert to trigger
    # e.g., it would set Nsta=0 for RSAM or relax all infrasound parameters

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
        # TODO: use logging module instead of redirecting stdout and stderr to a file
        # TODO: add log rotation to avoid filling up disk with logs
        # TODO: implement file locking to avoid multiple instances of the alarm running
        # TODO: implement kill switch
        # if run from a cron, write output to 4-hourly file in the logs directory
        T0 = utc.now()
        d_hour = int(T0.strftime("%H")) % 4
        f_time = utc(T0.strftime("%Y%m%d")) + (int(T0.strftime("%H")) - d_hour) * 3600
        file = Path(os.environ["LOGS_DIR"]) / f"{args.config}-{f_time.strftime('%Y%m%d-%H')}.log"
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
        # Load config directly from CONFIGS_DIR
        config_path = Path(os.environ.get("CONFIGS_DIR")) / f"{args.config}.py"
        spec = importlib.util.spec_from_file_location(args.config, config_path)
        config = importlib.util.module_from_spec(spec)
        sys.modules[args.config] = config
        spec.loader.exec_module(config)
        
        # Import and run the alarm
        ALARM = import_module(f"avo_alarms.alarm_codes.{config.alarm_type}")
        ALARM.run_alarm(
            config, T0,
            test_flag=args.test,
            mm_flag=args.mm,
            icinga_flag=args.icinga
        )
    except Exception:
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


if __name__ == "__main__":
    main()
