"""Validate alarm YAML configs against their per-alarm Pydantic schemas.

Intended for use in CI (in the separate configs repo) and for local checks.
Validates every alarm ``*.yml`` in a directory against the schema registered
for its ``alarm_type``, printing a per-file PASS/FAIL summary and exiting
non-zero if anything fails.

Usage
-----
    validate-configs [DIR] [--check-distribution] [--env-file PATH]

If ``DIR`` is omitted, the config directory is taken from the ``CONFIGS_DIR``
environment variable (resolved by ``load_environment``, which defaults it to
``<project>/config`` when unset).

With ``--check-distribution``, also cross-references the distribution list
against the phonebook: every recipient named in a distribution group must exist
in the phonebook. Paths come from ``DISTRIBUTION_FILE`` / ``PHONEBOOK_FILE``
(both defaulted by ``load_environment``).
"""

import argparse
import os
import sys
from pathlib import Path

import yaml

from volc_alarms.utils.config_schema import (
    NON_ALARM_FILES,
    ConfigValidationError,
    validate_config,
    validate_config_dir,
)
from volc_alarms.utils.setup_utils import load_environment


def parse_args():
    """
    Parse command-line arguments for the script.

    Returns:
        argparse.Namespace: Parsed arguments.
    """

    parser = argparse.ArgumentParser(
        prog="validate-configs",
        description="Validate alarm YAML configs against their Pydantic schemas.",
        epilog="e.g.: validate-configs ./config --check-distribution",
    )
    parser.add_argument(
        "dir",
        type=str,
        nargs="?",
        default=None,
        help="Directory of alarm config files. Defaults to CONFIGS_DIR.",
    )
    parser.add_argument(
        "--check-distribution",
        action="store_true",
        help=(
            "Also check that every recipient in the distribution list is "
            "defined in the phonebook."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )

    return parser.parse_args()


def check_distribution(distribution_file, phonebook_file):
    """Check that every distribution-list recipient exists in the phonebook.

    Parameters
    ----------
    distribution_file : str or Path
        Path to ``distribution.yml`` (groups mapping to lists of recipient
        names).
    phonebook_file : str or Path
        Path to ``phonebook.yml`` (recipient name -> contact mapping).

    Returns
    -------
    list[str]
        Human-readable error strings; empty when everything resolves.
    """
    distribution_file = Path(distribution_file)
    phonebook_file = Path(phonebook_file)

    errors = []

    for label, path in (("distribution", distribution_file), ("phonebook", phonebook_file)):
        if not path.is_file():
            errors.append(f"{label} file not found: {path}")
    if errors:
        return errors

    try:
        distribution = yaml.safe_load(distribution_file.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{distribution_file}: invalid YAML: {exc}"]
    try:
        phonebook = yaml.safe_load(phonebook_file.read_text()) or {}
    except yaml.YAMLError as exc:
        return [f"{phonebook_file}: invalid YAML: {exc}"]

    if not isinstance(distribution, dict):
        return [f"{distribution_file}: expected a mapping of groups to recipients"]
    if not isinstance(phonebook, dict):
        return [f"{phonebook_file}: expected a mapping of names to contacts"]

    known = set(phonebook)

    for group, recipients in distribution.items():
        if recipients is None:
            continue
        if not isinstance(recipients, list):
            errors.append(
                f"{distribution_file}: group '{group}' must be a list of "
                f"recipient names"
            )
            continue
        for name in recipients:
            if name not in known:
                errors.append(
                    f"{distribution_file}: recipient '{name}' in group "
                    f"'{group}' is not defined in {phonebook_file.name}"
                )

    return errors


def main():
    """Main entry point for the config validation script."""

    args = parse_args()

    load_environment(args.env_file)

    config_dir = Path(args.dir) if args.dir is not None else Path(os.environ["CONFIGS_DIR"])

    print(f"Validating alarm configs in: {config_dir}\n")

    had_failure = False

    # --- Per-file schema validation -------------------------------------
    try:
        results = validate_config_dir(config_dir)
        for path in sorted(results):
            print(f"  PASS  {path.name}")
    except ConfigValidationError as exc:
        had_failure = True
        # validate_config_dir may fail wholesale (missing dir) or report a set
        # of per-file errors; re-walk so passing files still show as PASS.
        if config_dir.is_dir():
            _report_per_file(config_dir)
        print(f"\n{exc}", file=sys.stderr)

    # --- Optional distribution <-> phonebook cross-reference ------------
    if args.check_distribution:
        print("\nChecking distribution list against phonebook...")
        dist_errors = check_distribution(
            os.environ["DISTRIBUTION_FILE"],
            os.environ["PHONEBOOK_FILE"],
        )
        if dist_errors:
            had_failure = True
            print("  FAIL  distribution/phonebook cross-reference")
            print("\n" + "\n".join(dist_errors), file=sys.stderr)
        else:
            print("  PASS  distribution/phonebook cross-reference")

    if had_failure:
        print("\nValidation FAILED.", file=sys.stderr)
        sys.exit(1)

    print("\nAll configs valid.")


def _report_per_file(config_dir):
    """Print a PASS/FAIL line per alarm config (best-effort, for display)."""
    for yml in sorted(Path(config_dir).glob("*.yml")):
        if yml.name in NON_ALARM_FILES:
            continue
        try:
            validate_config(yml)
            print(f"  PASS  {yml.name}")
        except ConfigValidationError:
            print(f"  FAIL  {yml.name}")


if __name__ == "__main__":
    main()
