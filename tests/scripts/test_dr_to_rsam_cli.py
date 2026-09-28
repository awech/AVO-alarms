"""Unit tests for the ``dr-to-rsam`` command-line entry point.

Cover the argument parsing/validation and the ``main()`` dispatch into
``Dr_to_RSAM`` with all boundaries mocked (no FDSN, no config file, no logging
setup).

Covered:
* parse_args       — DR positional; --config vs --nslc/--volcano validation
* main()           — loads config when --config given; forwards args to Dr_to_RSAM
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from volc_alarms.scripts import dr_to_rsam as cli

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------
def test_parse_args_accepts_dr_with_config(monkeypatch):
    """parse_args reads the DR float and a --config name."""
    monkeypatch.setattr(sys, "argv", ["dr-to-rsam", "2.0", "--config", "Pavlof_RSAM"])
    args = cli.parse_args()
    assert args.DR == 2.0
    assert args.config == "Pavlof_RSAM"


def test_parse_args_accepts_nslc_with_volcano(monkeypatch):
    """parse_args reads one or more --nslc values together with --volcano."""
    monkeypatch.setattr(
        sys, "argv",
        ["dr-to-rsam", "3.5", "--volcano", "Pavlof", "--nslc", "AV.PN7A.--.BHZ", "AV.PS4A.--.BHZ"],
    )
    args = cli.parse_args()
    assert args.DR == 3.5
    assert args.volcano == "Pavlof"
    assert args.nslc == ["AV.PN7A.--.BHZ", "AV.PS4A.--.BHZ"]


def test_parse_args_requires_config_or_nslc(monkeypatch):
    """parse_args errors (SystemExit) when neither --config nor --nslc is given."""
    monkeypatch.setattr(sys, "argv", ["dr-to-rsam", "2.0"])
    with pytest.raises(SystemExit):
        cli.parse_args()


def test_parse_args_nslc_requires_volcano(monkeypatch):
    """parse_args errors when --nslc is given without --volcano."""
    monkeypatch.setattr(sys, "argv", ["dr-to-rsam", "2.0", "--nslc", "AV.PN7A.--.BHZ"])
    with pytest.raises(SystemExit):
        cli.parse_args()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def test_main_forwards_args_to_dr_to_rsam(monkeypatch):
    """main() loads env/logging, loads the config, and calls Dr_to_RSAM with the args."""
    calls = {}

    monkeypatch.setattr(sys, "argv", ["dr-to-rsam", "2.0", "--config", "Pavlof_RSAM", "--base", "50"])
    monkeypatch.setattr(cli, "load_environment", lambda env_file=None: None)
    monkeypatch.setattr(cli, "setup_root_logger", lambda *a, **k: None)
    monkeypatch.setattr(cli, "load_config", lambda name: SimpleNamespace(alarm_name=name))

    def _dr_to_rsam(DR, config=None, nslc_list=None, volcano=None, base=25):
        calls.update(DR=DR, config=config, nslc_list=nslc_list, volcano=volcano, base=base)

    monkeypatch.setattr(cli, "Dr_to_RSAM", _dr_to_rsam)

    cli.main()

    assert calls["DR"] == 2.0
    assert calls["base"] == 50
    assert calls["config"].alarm_name == "Pavlof_RSAM"
    assert calls["nslc_list"] is None
