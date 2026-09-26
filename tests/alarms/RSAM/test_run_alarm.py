"""Integration test: RSAM ``run_alarm()`` end to end vs frozen baseline.

Drives the RSAM alarm through the shared fakes harness and compares its
observable behavior (Icinga state, Mattermost/email sends, DB writes, file
cleanup, call order) against the frozen JSON baseline.

Scenarios:
* representative - default zero-filled waveforms -> "RSAM data missing!" WARNING
* critical       - crafted hot source stations + quiet arrestor -> CRITICAL send
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize("name", ["RSAM_representative", "RSAM_critical"])
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """RSAM.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
