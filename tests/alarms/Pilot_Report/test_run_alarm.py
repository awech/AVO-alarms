"""Integration test: Pilot_Report ``run_alarm()`` end to end vs frozen baseline.

Scenario:
* representative - download returns ("OK", None) -> "No new pilot reports" OK
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
def test_run_alarm_matches_baseline(alarm_doubles, load_alarm_config):
    """Pilot_Report.run_alarm() representative behavior matches its frozen baseline."""
    run_and_compare("Pilot_Report_representative", alarm_doubles, load_alarm_config)
