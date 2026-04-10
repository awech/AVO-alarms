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
from ..utils.logging_config import get_logger


def main():
    """Main entry point for the alarm runner."""
    
    start = time.time()
    load_dotenv()
    
    # Initialize logger
    logger = get_logger(__name__)
    
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
        logger.info("Running alarm in test mode")

    # TODO: implement file locking to avoid multiple instances of the alarm running
    # TODO: implement kill switch
    if os.getenv("FROMCRON") == "yep":
        # create a logger with config name for file logging
        logger = get_logger(__name__, log_dir=os.environ.get("LOGS_DIR"), config_name=args.config)
        # keep .keep file from getting pruned by other cron deleting old log-files
        keep_file = Path(os.environ["LOGS_DIR"]) / ".keep"
        os.system(f"touch {keep_file}")

    logger.info("\n-----------------------------------------")

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
        logger.error("Error...")
        b = traceback.format_exc()
        message = "".join(f"{a}\n" for a in b.splitlines())
        message = f"{str(T0)}\n\n{message}"
        subject = config.alarm_name + " error"
        filename = Path("alarm_aux_files") / "oops.jpg"
        messaging.send_alert("Error", subject, message, attachment=filename)

    end = time.time()
    logger.info(f"[{end - start:.2f} seconds to complete alarm]")
    logger.info("-----------------------------------------\n")


if __name__ == "__main__":
    main()
