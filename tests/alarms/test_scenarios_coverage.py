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
    # Each SCENARIOS entry carries its alarm module explicitly as the first item
    # of the (module, driver) value, so read the covered set from there rather
    # than parsing scenario-name strings (module names and variants both contain
    # "_", e.g. "NOAA_CIMSS-representative", "Infrasound-not_enough_channels").
    covered = {module for module, _driver in SCENARIOS.values()}
    missing = alarm_types - covered
    assert not missing, f"Alarms without a baseline scenario: {sorted(missing)}"
