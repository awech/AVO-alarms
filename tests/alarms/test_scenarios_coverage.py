"""Suite-level sanity check: every alarm has at least one integration scenario.

Guards against adding a new alarm without a corresponding ``run_alarm()``
baseline scenario in ``tests/_harness/scenarios.py``.
"""

from __future__ import annotations

import pytest

from tests._harness.scenarios import SCENARIOS


@pytest.mark.integration
def test_every_alarm_has_a_scenario():
    """Each alarm type has at least a representative baseline scenario."""
    alarm_types = {
        "Infrasound", "RSAM", "Tremor", "Lightning", "NOAA_CIMSS",
        "Pilot_Report", "SO2", "Swarm", "Magnitude", "VAA",
    }
    # Scenario names are "<AlarmType>_<variant>" where <variant> may itself
    # contain underscores (e.g. "Infrasound_not_enough_channels"), so match by
    # alarm-type prefix rather than splitting on the last underscore.
    missing = {
        atype
        for atype in alarm_types
        if not any(name == atype or name.startswith(f"{atype}_") for name in SCENARIOS)
    }
    assert not missing, f"Alarms without a baseline scenario: {sorted(missing)}"
