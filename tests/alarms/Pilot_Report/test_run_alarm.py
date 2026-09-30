"""Integration test: Pilot_Report ``run_alarm()`` end to end vs frozen baseline.

Drives the Pilot_Report alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* critical          - recorded urgent Shishaldin ash PIREP -> CRITICAL + send
* non_urgent        - same report, URGENT flipped to 'F' -> WARNING + send
* api_error         - download returns ('WARNING', None) -> PIREP API error WARNING
* no_reports        - download returns ('OK', None) -> "No new pilot reports" OK
* already_processed - the recorded report, already in the DB -> OK

The critical/non_urgent/already_processed scenarios feed a real PIREP shapefile
ZIP so the genuine shapefile parse + find_nearest_volcano + volcano-mention
trigger all run; the figure render is unit-tested in test_figure.py.
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Pilot_Report-critical",
        "Pilot_Report-non_urgent",
        "Pilot_Report-api_error",
        "Pilot_Report-no_reports",
        "Pilot_Report-already_processed",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Pilot_Report.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
