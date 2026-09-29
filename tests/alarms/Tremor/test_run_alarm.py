"""Integration test: Tremor ``run_alarm()`` end to end vs frozen baseline.

Drives the Tremor alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline. All scenarios replay the
same recorded Pavlof event through the real enveloc solver, differing only in
how many prior events are seeded into the tremor DB (via record_tremor_event_ids)
and small config tweaks that steer run_alarm down each outcome branch.

Scenarios:
* data_missing          - only 2 live channels -> "Data missing!" WARNING
* normal                - real detection, empty prior DB -> OK "Seismicity normal"
* elevated              - +4 prior events -> "Elevated seismicity" WARNING
* elevated_no_new_events- prior events high, noise -> no new events -> WARNING
* low_amplitude         - duration high but RSAM gate fails -> low-amplitude WARNING
* missing_rsam_station  - rsam_station absent -> fires + error alert (CRITICAL)
* critical              - duration + passing RSAM gate -> CRITICAL + full send
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Tremor_data_missing",
        "Tremor_normal",
        "Tremor_elevated",
        "Tremor_elevated_no_new_events",
        "Tremor_low_amplitude",
        "Tremor_missing_rsam_station",
        "Tremor_critical",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Tremor.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
