"""Shared driver for the per-alarm integration tests.

Each ``tests/alarms/<Alarm>/test_run_alarm.py`` is a thin wrapper that calls
``run_and_compare(name, alarm_doubles, load_alarm_config)`` for its scenario(s).
This keeps the actual drive -> snapshot -> compare logic in one place so every
alarm's integration test behaves identically.

Behavior:
* Runs the named scenario (from ``scenarios.SCENARIOS``) with the shared doubles.
* Captures the observable behavior into a deterministic dict.
* Asserts the alarm resolved to a real detection state.
* In REGEN mode (``REGEN_BASELINES=1``) freezes the baseline and skips.
* Otherwise compares the captured behavior against the frozen JSON baseline.
"""

from __future__ import annotations

import os

import pytest

from tests._harness import snapshot_utils
from tests._harness.scenarios import SCENARIOS

REGEN = os.environ.get("REGEN_BASELINES") == "1"

VALID_STATES = {"OK", "WARNING", "CRITICAL"}


def run_and_compare(name, alarm_doubles, load_alarm_config):
    """Drive scenario ``name``, snapshot its behavior, and freeze-or-compare.

    Args:
        name: a key in ``scenarios.SCENARIOS`` (e.g. ``"RSAM_critical"``).
        alarm_doubles: the installed fakes handle (``alarm_doubles`` fixture).
        load_alarm_config: the config loader factory (``load_alarm_config``).
    """
    scenario = SCENARIOS[name]

    # Drive the current alarm's run_alarm with recorded fixtures + doubles.
    scenario(alarm_doubles, load_alarm_config)

    # Snapshot the observable behavior (state, icinga, messages, record_send
    # fields, os.remove cleanup, call order) deterministically.
    captured = snapshot_utils.capture(alarm_doubles)

    # Every scenario must reach an Icinga heartbeat carrying a resolved state.
    assert captured["detection_state"] in VALID_STATES, (
        f"{name}: scenario did not resolve to a detection state "
        f"(call order: {captured['call_order']})"
    )

    path = snapshot_utils.baseline_path(name)

    if REGEN or not path.exists():
        snapshot_utils.freeze_baseline(name, captured)
        if REGEN:
            pytest.skip(f"Regenerated frozen baseline: {path.name}")
        # First-time bootstrap: file was just created from current code.
        return

    frozen = snapshot_utils.load_baseline(name)
    assert captured == frozen, (
        f"{name}: current behavior diverged from the frozen baseline.\n"
        f"Frozen:   {frozen}\n"
        f"Captured: {captured}"
    )
