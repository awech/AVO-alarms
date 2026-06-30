"""Command-line entry point for running volcano monitoring alarms."""

import argparse
import os
import time
import traceback
from importlib import import_module
from importlib.resources import files
from pathlib import Path

from obspy import UTCDateTime as utc

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import (
    LockFile,
    get_logger,
    load_config,
    load_environment,
    setup_root_logger,
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
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
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
        "--earthscope",
        help="Use Earthscope FDSN client instead of Winston for waveform downloads",
        action="store_true",
    )
    parser.add_argument(
        "--mm",
        help="Post to mattermost (off unless this flag is passed)",
        action="store_true",
    )
    parser.add_argument(
        "--icinga",
        help="Send heartbeat to icinga (off unless this flag is passed)",
        action="store_true",
    )

    return parser.parse_args()


def update_arguments(args):

    if args.force:
        args.test = True

    if args.time is None:
        T0 = utc.utcnow()  # no time given, use current timestamp
        args.time = utc(T0.strftime("%Y-%m-%d %H:%M"))  # round down to the nearest minute
    else:
        args.time = utc(args.time)

    return args


def main():
    """Main entry point for the alarm runner."""
    
    start = time.time()

    args = parse_args()

    # Load environment: explicit --env-file if given, otherwise search upward.
    load_environment(args.env_file)

    # If --earthscope flag is set, use Earthscope FDSN client for waveform downloads
    if args.earthscope:
        os.environ["USE_EARTHSCOPE"] = "1"
    
    # Set up root logger first (before locking, for error messages)
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.getenv("LOGS_DIR"), config_name=args.config)
        # keep .keep file from getting pruned by other cron deleting old log-files
        keep_file = Path(os.getenv("LOGS_DIR")) / ".keep"
        keep_file.touch(exist_ok=True)
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

    # Kill switch: if `kill: true` is in the config, send icinga warning and exit
    config = load_config(args.config)
    if getattr(config, "kill", False):
        logger.warning(f"Kill switch active for {args.config} — skipping alarm")
        messaging.icinga(config, "WARNING", f"{args.config} alarm has been killed")
        lock.release()
        return

    args = update_arguments(args)
    if args.test:
        # e.g., it would set Nsta=0 for RSAM or relax all infrasound parameters
        logger.info("Running alarm in test mode")

    logger.info(f"---- Running {args.config} at {args.time.strftime('%Y-%m-%d %H:%M:%S')} ----")

    try:
        # Import and run the alarm
        ALARM = import_module(f"volc_alarms.alarms.{config.alarm_type}")
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
        filename = files("volc_alarms.data").joinpath("oops.jpg")
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
