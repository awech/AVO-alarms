"""Command-line entry point for listing recorded alarm sends.

Queries the sent-events database and prints matching entries, filtered by
alarm name, volcano, and/or a UTC time range (given as explicit start/end
times or as a duration before present). Exposed as the ``list-alerts``
console script.
"""

import argparse

import pandas as pd
from obspy import UTCDateTime as utc

from volc_alarms.utils import alarming
from volc_alarms.utils.setup_utils import load_environment


def parse_args():
    """Parse command-line arguments for the alert lister.

    Returns
    -------
    argparse.Namespace
        Parsed arguments with the following attributes:

        alarm : str or None
            Alarm name to filter by, with ``_`` standing in for spaces.
        volcano : str or None
            Volcano name to filter by, with ``_`` standing in for spaces.
        test : bool
            If True, query the ``test_sent_events`` table instead of the
            production table.
        starttime : str or None
            Window start in UTC, formatted ``YYYYMMDDHHMM``.
        endtime : str or None
            Window end in UTC, formatted ``YYYYMMDDHHMM``.
        duration : str or None
            Window length before present as a number plus unit: ``h`` (hours),
            ``d`` (days), or ``m`` (minutes), e.g. ``"3h"``. Combined with
            ``starttime`` or ``endtime``, or used alone relative to now.
        env_file : str or None
            Path to a ``.env`` file; if omitted, the directory tree is
            searched upward.
    """
    
    parser = argparse.ArgumentParser(
        prog="list-alerts",
        epilog="e.g.: list-alerts -a Pavlof_RSAM or list-alerts -s  201701020205 -e 201701020205 -v Pavlof"
    )
    parser.add_argument(
        "-a",
        "--alarm",
        type=str,
        help="Alarm name. Use '_' in place of spaces.",
        required=False,
    )
    parser.add_argument(
        "-v",
        "--volcano",
        type=str,
        help="Volcano name. Use '_' in place of spaces.",
        required=False,
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Flag to query `test_sent_events` table. Defaults to False",
        required=False,
    )
    parser.add_argument(
        "-s",
        "--starttime",
        type=str,
        help="Start time in UTC: YYYYMMDDHHMM",
        required=False,
    )
    parser.add_argument(
        "-e",
        "--endtime",
        type=str,
        help="End time in UTC: YYYYMMDDHHMM",
        required=False,
    )
    parser.add_argument(
        "-dt",
        "--duration",
        type=str,
        help="Duration in hours (\"h\"), days (\"d\"), or minutes (\"m\") before present to process (e.g. -dt 3h)",
        required=False,
    )
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )

    return parser.parse_args()


def main():
    """Query and print recorded alarm sends from the command line.

    Resolves the time window from the ``starttime``/``endtime``/``duration``
    arguments (validating that they are mutually consistent), builds a filter
    from the alarm name and volcano, and prints the matching sent-events rows
    via :func:`volc_alarms.utils.alarming.filtered_list`.

    Notes
    -----
    Intended to be invoked via the ``list-alerts`` console script. Reads
    arguments from the command line and takes no parameters.

    Raises
    ------
    ValueError
        If the start time is after the end time, or if a duration is given
        together with both a start and end time.
    """
    args = parse_args()  # Parse command-line arguments

    load_environment(args.env_file)

    if args.starttime is not None:
        T1 = utc(args.starttime)
    if args.endtime is not None:
        T2 = utc(args.endtime)
    if args.starttime is not None and args.endtime is not None:
        if T1 > T2:
            raise ValueError("Start time must be before end time.")
        if args.duration is not None:
            raise ValueError("Cannot have start, end AND duration")

    if args.duration is not None:
        duration_value = args.duration[:-1]
        if args.duration.endswith("h"):
            dt = pd.Timedelta(hours=int(duration_value))
        elif args.duration.endswith("d"):
            dt = pd.Timedelta(days=int(duration_value))
        elif args.duration.endswith("m"):
            dt = pd.Timedelta(minutes=int(duration_value))
        else:
            raise ValueError("Invalid duration format. Use 'h' for hours or 'd' for days.")

        if args.starttime is not None:
            T2 = T1 + dt
        elif args.endtime is not None:
            T1 = T2 - dt
        else:
            T2 = utc.utcnow()
            T1 = T2 - dt

    query_dict = {"t1": "2000-01-01"}
    if "T1" in locals():
        query_dict.update({"t1": T1.strftime("%Y-%m-%dT%H:%M:%S")})
    if "T2" in locals():
        query_dict.update({"t2": T2.strftime("%Y-%m-%dT%H:%M:%S")})
    if args.alarm is not None:
        alarm_name = args.alarm.replace("_", " ")
        query_dict.update({"alarm_id": alarm_name})
    if args.volcano is not None:
        v_name = args.volcano.replace("_", " ")
        query_dict.update({"volcano": v_name})

    print("\n")
    alarming.filtered_list(query_dict, test=args.test)
    print("\n")


if __name__ == "__main__":
    main()