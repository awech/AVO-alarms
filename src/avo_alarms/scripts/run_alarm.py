"""Command-line entry point for running volcano monitoring alarms."""

import argparse
import os
import time
import traceback
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from avo_alarms.utils import messaging
from avo_alarms.utils.setup_utils import (
    get_logger,
    load_config,
    setup_root_logger,
    update_arguments,
    LockFile,
)


def parse_args():
    """
    Parse command-line arguments for the script.
    
    Returns:
        argparse.Namespace: Parsed arguments.
    """

    parser = argparse.ArgumentParser(
        prog="run-alarm",
        epilog="e.g.: `run-alarm avlof_RSAM` or `run-alarm --test -t 201701020205 -c Pavlof_RSAM`",
    )
    parser.add_argument("config", type=str, help="Name of the config file")
    parser.add_argument(
        "-t",
        "--time",
        type=str,
        help="utc time stamp:YYYYMMDDHHMM (optional, otherwise grabs current utc time)",
        required=False,
    )
    parser.add_argument("--test", help="Run in test mode", action="store_true")
    parser.add_argument(
        "--force", help="Force a trigger in test mode", action="store_true"
    )
    parser.add_argument(
        "--mm",
        help="Post to mattermost",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--icinga",
        help="Send heartbeat to icinga",
        action=argparse.BooleanOptionalAction,
        default=None,
    )

    return parser.parse_args()



def main():
    """Main entry point for the alarm runner."""
    
    start = time.time()
    load_dotenv()

    args = parse_args()
    
    # Set up root logger first (before locking, for error messages)
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.getenv("LOGS_DIR"), config_name=args.config)
        # keep .keep file from getting pruned by other cron deleting old log-files
        keep_file = Path(os.getenv("LOGS_DIR")) / ".keep"
        keep_file.touch(exist_ok=True)
        # TODO: add default lock & logs directories. Set even if not in .env file
        if "LOCK_DIR" in os.environ:
            lock_dir = os.getenv("LOCK_DIR")
        else:
            lock_dir = os.getenv("LOGS_DIR")
    else:
        setup_root_logger()
        lock_dir = Path.home() / ".tmp" / "alarms"

    logger = get_logger(__name__)

    # Implement file locking to avoid multiple instances of the same alarm running
    try:
        lock = LockFile(lock_dir, args.config)
        lock.acquire()
    except RuntimeError as e:
        logger.warning(str(e))
        return

    # TODO: implement kill switch

    args = update_arguments(args)
    if args.test:
        # e.g., it would set Nsta=0 for RSAM or relax all infrasound parameters
        logger.info("Running alarm in test mode")

    logger.info(f"---- Running {args.config} at {args.time.strftime('%Y-%m-%d %H:%M:%S')} ----")

    try:
        # load the config file from args
        config = load_config(args.config)
        
        # Import and run the alarm
        ALARM = import_module(f"avo_alarms.alarm_codes.{config.alarm_type}")
        ALARM.run_alarm(
            config, args.time,
            test_flag=args.test,
            mm_flag=args.mm,
            icinga_flag=args.icinga,
            force_flag=args.force
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
    finally:
        # Always release the lock
        lock.release()

    end = time.time()
    sep_string = "\n-----------------------------------------\n"
    sep_string+= "\n-----------------------------------------"
    logger.info(f"[{end - start:.2f} seconds to complete alarm]{sep_string}")
    
    # logger.info(sep_string)

if __name__ == "__main__":
    main()
