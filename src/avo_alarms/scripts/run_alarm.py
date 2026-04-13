"""Command-line entry point for running volcano monitoring alarms."""

import argparse
import os
import time
import traceback
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from ..utils import messaging
from ..utils.setup_utils import (
    get_logger,
    load_config,
    setup_root_logger,
    update_arguments,
)


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
    

    # TODO: implement file locking to avoid multiple instances of the alarm running
    # TODO: implement kill switch
    # TODO: add "force trigger" (or similar) argument to force an alert to trigger

    if os.getenv("FROMCRON") == "yep":
        # Set up root logger with file handler for this alarm configuration
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name=args.config)
        # keep .keep file from getting pruned by other cron deleting old log-files
        keep_file = Path(os.environ["LOGS_DIR"]) / ".keep"
        keep_file.touch(exist_ok=True)
    else:
        setup_root_logger()

    logger = get_logger(__name__)

    args = update_arguments(args)
    if args.test:
        # e.g., it would set Nsta=0 for RSAM or relax all infrasound parameters
        logger.info("Running alarm in test mode")

    logger.info(f"---- Running {args.config} at {args.time} ----")

    try:
        # load the config file from args
        config = load_config(args.config)
        
        # Import and run the alarm
        ALARM = import_module(f"avo_alarms.alarm_codes.{config.alarm_type}")
        ALARM.run_alarm(
            config, args.time,
            test_flag=args.test,
            mm_flag=args.mm,
            icinga_flag=args.icinga
        )
    except Exception:
        # if error, send message to designated recipients
        logger.error("Error...")
        b = traceback.format_exc()
        message = "".join(f"{a}\n" for a in b.splitlines())
        message = f"{str(args.time)}\n\n{message}"
        subject = config.alarm_name + " error"
        filename = Path("alarm_aux_files") / "oops.jpg"
        messaging.send_alert("Error", subject, message, attachment=filename)

    end = time.time()
    logger.info(f"[{end - start:.2f} seconds to complete alarm]")
    sep_string = "\n-----------------------------------------\n"
    sep_string+= "\n-----------------------------------------"
    logger.info(sep_string)

if __name__ == "__main__":
    main()
