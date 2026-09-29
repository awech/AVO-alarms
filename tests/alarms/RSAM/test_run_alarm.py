"""Integration test: RSAM ``run_alarm()`` end to end vs frozen baseline.

Drives the RSAM alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline. All five scenarios replay
the same recorded Pavlof event, differing only in a small config tweak that
steers run_alarm down each outcome branch.

Scenarios:
* critical      - real event, unmodified config -> CRITICAL detection + full send
* elevated      - thresholds x2 -> "RSAM elevated!" WARNING
* arrested      - lowered arrestor threshold -> "RSAM normal (arrested)" WARNING
* normal        - thresholds x10 -> "RSAM normal." OK
* data_missing  - only 2 live source channels -> "RSAM data missing!" WARNING
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "RSAM-critical",
        "RSAM-elevated",
        "RSAM-arrested",
        "RSAM-normal",
        "RSAM-data_missing",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """RSAM.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
