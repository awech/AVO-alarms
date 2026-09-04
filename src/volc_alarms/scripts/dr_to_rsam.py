"""Command-line entry point for computing RSAM count levels from a target
reduced displacement (DR) using :func:`volc_alarms.utils.processing.Dr_to_RSAM`.

Two modes of operation:

1. From an alarm config (provides volcano name + station list)::

       dr-to-rsam 2.0 --config Pavlof_RSAM

2. From explicit station(s) + volcano name::

       dr-to-rsam 2.0 --volcano Pavlof --nslc AV.PN7A.--.BHZ
       dr-to-rsam 2.0 --volcano Pavlof --nslc AV.PN7A.--.BHZ AV.PS4A.--.BHZ
"""

import argparse

from volc_alarms.utils.processing import Dr_to_RSAM
from volc_alarms.utils.setup_utils import (
    get_logger,
    load_config,
    load_environment,
    setup_root_logger,
)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="dr-to-rsam",
        description="Convert a target reduced displacement (DR) to RSAM count "
        "levels for one or more stations.",
        epilog="e.g.: `dr-to-rsam 2.0 --config Pavlof_RSAM` or "
        "`dr-to-rsam 2.0 --volcano Pavlof --nslc AV.PN7A.--.BHZ`",
    )
    parser.add_argument(
        "DR",
        type=float,
        help="Target reduced displacement (cm^2).",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Name of an alarm config file (provides volcano name and station "
        "list). Mutually exclusive with --nslc/--volcano.",
        required=False,
    )
    parser.add_argument(
        "--nslc",
        type=str,
        nargs="+",
        help="One or more NSLC strings, e.g. AV.PN7A.--.BHZ. Requires --volcano.",
        required=False,
    )
    parser.add_argument(
        "--volcano",
        type=str,
        help="Volcano name (used with --nslc, or to override the config volcano).",
        required=False,
    )
    parser.add_argument(
        "--base",
        type=int,
        default=25,
        help="Rounding base for the output levels (default: 25).",
    )
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree).",
        required=False,
    )

    args = parser.parse_args()

    if not args.config and not args.nslc:
        parser.error("provide either --config or --nslc (with --volcano)")
    if args.nslc and not args.volcano:
        parser.error("--nslc requires --volcano")

    return args


def main():
    """Main entry point for the DR-to-RSAM converter."""

    args = parse_args()

    load_environment(args.env_file)
    setup_root_logger()

    logger = get_logger(__name__)

    config = load_config(args.config) if args.config else None

    logger.info(f"Computing RSAM levels for DR={args.DR:g} cm^2 (rounded to {args.base:g})")

    Dr_to_RSAM(
        args.DR,
        config=config,
        nslc_list=args.nslc,
        volcano=args.volcano,
        base=args.base,
    )


if __name__ == "__main__":
    main()
