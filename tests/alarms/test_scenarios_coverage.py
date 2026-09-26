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
    # Scenario names are "<AlarmType>_<variant>"; strip the trailing variant.
    covered = {n.rsplit("_", 1)[0] for n in SCENARIOS}
    missing = alarm_types - covered
    assert not missing, f"Alarms without a baseline scenario: {sorted(missing)}"
