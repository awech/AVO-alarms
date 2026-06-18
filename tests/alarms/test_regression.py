"""Golden behavior-baseline tests.

Each alarm scenario is run offline with deterministic doubles, and its
observable behavior (Icinga state, messages, DB records, file cleanup) is
captured and compared against a frozen JSON baseline.

Usage:
    pytest tests/alarms/test_baselines.py          # Verify baselines
    REGEN_BASELINES=1 pytest tests/alarms/test_baselines.py  # Regenerate

Only regenerate baselines intentionally when you've changed alarm behavior.
Review the JSON diffs before committing.
"""

from __future__ import annotations

import os

import pytest

from tests.alarms import snapshot_utils
from tests.alarms.scenarios import SCENARIOS

REGEN = os.environ.get("REGEN_BASELINES") == "1"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_behavior_baseline(name, alarm_doubles, load_alarm_config):
    """Drive a scenario, snapshot its behavior, and freeze or compare."""
    scenario = SCENARIOS[name]

    # Drive the current alarm's run_alarm with recorded fixtures + doubles.
    scenario(alarm_doubles, load_alarm_config)

    # Snapshot the observable Behavior_Baseline (state, icinga, message,
    # record_send fields, os.remove cleanup) deterministically.
    captured = snapshot_utils.capture(alarm_doubles)

    # Every scenario must reach an Icinga heartbeat carrying a resolved state.
    assert captured["detection_state"] in {"OK", "WARNING", "CRITICAL"}, (
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


def test_all_alarms_have_a_scenario():
    """Sanity: every alarm_type has at least a representative baseline scenario."""
    alarm_types = {
        "Infrasound", "RSAM", "Tremor", "Lightning", "NOAA_CIMSS",
        "Pilot_Report", "SO2", "Swarm", "Magnitude", "VAA",
    }
    # Scenario names are "<AlarmType>_<variant>"; strip the trailing variant.
    covered = {n.rsplit("_", 1)[0] for n in SCENARIOS}
    missing = alarm_types - covered
    assert not missing, f"Alarms without a baseline scenario: {sorted(missing)}"
