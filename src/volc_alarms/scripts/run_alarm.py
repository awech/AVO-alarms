"""Command-line entry point for running volcano monitoring alarms.

Loads an alarm config by name, sets up logging and single-instance locking,
then dynamically dispatches to the matching ``volc_alarms.alarms.<type>``
module's ``run_alarm``. Supports an optional UTC timestamp and test, force,
Earthscope, Mattermost, and Icinga flags::

    run-alarm Pavlof_RSAM
    run-alarm --test -t 201701020205 Pavlof_RSAM

Exposed as the ``run-alarm`` console script.
"""

import argparse
import os
import time
import traceback
from importlib import import_module
from importlib.resources import files
from pathlib import Path


def parse_args():
    """Parse command-line arguments for the alarm runner.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        config : str
            Name of the alarm config file to run.
        time : str or None
            UTC timestamp formatted ``YYYYMMDDHHMM``. If omitted, the current
            UTC time is used.
        test : bool
            If True, run in test mode (test tables/channels, TEST watermark).
        force : bool
            If True, force a trigger; also implies ``test`` mode.
        earthscope : bool
            If True, use the Earthscope FDSN client for waveform downloads
            instead of Winston.
        mm : bool
            If True, post to Mattermost (off by default).
        icinga : bool
            If True, send a heartbeat to Icinga (off by default).
        env_file : str or None
            Path to a ``.env`` file; if omitted, the directory tree is
            searched upward.
    """
    parser = argparse.ArgumentParser(
        prog="run-alarm",
        epilog="e.g.: `run-alarm Pavlof_RSAM` or `run-alarm --test -t 201701020205 Pavlof_RSAM`",
    )
    parser.add_argument(
        "config",
        type=str,
        help="Name of the config file in CONFIGS_DIR, with or without the "
        ".yml/.yaml extension (e.g. 'RSAM' or 'RSAM.yml')",
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
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )

    return parser.parse_args()


def update_arguments(args):
    """Normalize parsed arguments before running an alarm.

    Forces ``test`` mode on when ``force`` is set, and resolves ``time`` to an
    ``obspy.UTCDateTime``: the current time rounded down to the minute when no
    timestamp was given, otherwise the parsed timestamp.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments from :func:`parse_args`.

    Returns
    -------
    argparse.Namespace
        The same namespace with ``test`` and ``time`` normalized.
    """
    from obspy import UTCDateTime as utc

    if args.force:
        args.test = True

    if args.time is None:
        T0 = utc.utcnow()  # no time given, use current timestamp
        args.time = utc(T0.strftime("%Y-%m-%d %H:%M"))  # round down to the nearest minute
    else:
        args.time = utc(args.time)

    return args


def main():
    """Run a single alarm from the command line.

    Orchestrates one end-to-end alarm run:

    1. Parse arguments and load the environment (``--env-file`` or an upward
       search).
    2. Optionally switch waveform downloads to the Earthscope FDSN client
       (``--earthscope``).
    3. Configure the root logger (rotating file logs under cron, else
       console) and choose a lock directory.
    4. Acquire a :class:`~volc_alarms.utils.setup_utils.LockFile` so only one
       instance of this config runs at a time; exit early if already locked.
    5. Load the config and honor its kill switch (send an Icinga warning and
       exit when ``kill: true``).
    6. Dynamically import the module for ``config.alarm_type`` and call its
       ``run_alarm``, forwarding the test/mm/icinga/force flags.
    7. On any exception, email an error alert to the ``Error`` recipients;
       always release the lock and log the elapsed time.

    Notes
    -----
    Intended to be invoked via the ``run-alarm`` console script. Reads
    arguments from the command line and takes no parameters.
    """

    from volc_alarms.utils import messaging
    from volc_alarms.utils.setup_utils import (
        LockFile,
        get_logger,
        load_config,
        load_environment,
        setup_root_logger,
    )

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

    args = update_arguments(args)
    # Kill switch: if `kill: true` is in the config, send icinga warning and exit
    config = load_config(args.config)
    if getattr(config, "kill", False):
        logger.warning(f"Kill switch active for {args.config} — skipping alarm")
        messaging.icinga(
            config,
            "WARNING",
            f"{args.time.strftime('%Y-%m-%d %H:%M')} (UTC) Alarm has been killed",
            send=args.icinga,
        )
        lock.release()
        return

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
    except Exception:  # noqa: BLE001
        # if error, send message to designated recipients
        logger.error("Error...")
        b = traceback.format_exc()
        message = "".join(f"{a}\n" for a in b.splitlines())
        message = f"{args.time!s}\n\n{message}"
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
