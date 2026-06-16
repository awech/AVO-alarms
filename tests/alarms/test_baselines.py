"""Capture & freeze golden behavior baselines from the current code (task 1.2).

This is the SECOND gating task of the restructure. It runs against the
**pre-restructure** code and freezes each alarm's ``Behavior_Baseline`` as a JSON
fixture under ``baselines/``. Later golden tests (tasks 5.x / 7.x / 9.x) recapture
the same scenarios against the restructured packages and assert equality against
these frozen snapshots (Req 9.1-9.5, 12.2, 12.3).

Reproducible regeneration
--------------------------
Run normally to *verify* the current code still matches the frozen baselines::

    pytest tests/alarms/test_baselines.py

Set ``REGEN_BASELINES=1`` to (re)generate the frozen fixtures from the current
code (do this only intentionally, before any refactor)::

    REGEN_BASELINES=1 pytest tests/alarms/test_baselines.py

Each scenario is driven offline and deterministically: a fixed ``T0``, ``FROMCRON``
unset (no sleeps / time backup), and every external side effect replaced by the
shared doubles. The captured snapshot is therefore stable across regenerations.
"""

from __future__ import annotations

import os

import pytest

from tests.alarms import baseline_utils
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
    captured = baseline_utils.capture(alarm_doubles)

    # Every scenario must reach an Icinga heartbeat carrying a resolved state.
    assert captured["detection_state"] in {"OK", "WARNING", "CRITICAL"}, (
        f"{name}: scenario did not resolve to a detection state "
        f"(call order: {captured['call_order']})"
    )

    path = baseline_utils.baseline_path(name)

    if REGEN or not path.exists():
        baseline_utils.freeze_baseline(name, captured)
        if REGEN:
            pytest.skip(f"Regenerated frozen baseline: {path.name}")
        # First-time bootstrap: file was just created from current code.
        return

    frozen = baseline_utils.load_baseline(name)
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
