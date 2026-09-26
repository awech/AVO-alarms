"""Integration test: Magnitude ``run_alarm()`` end to end vs frozen baseline.

Drives the Magnitude alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* representative - empty FDSN catalog -> "No new earthquakes" OK
* critical       - crafted event near Pavlof -> CRITICAL detection + send
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize("name", ["Magnitude_representative", "Magnitude_critical"])
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Magnitude.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
