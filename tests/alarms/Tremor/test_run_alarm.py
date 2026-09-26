"""Integration test: Tremor ``run_alarm()`` end to end vs frozen baseline.

Scenario:
* representative - empty tremor DB + zero-filled waveforms -> "Data missing!" WARNING
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
def test_run_alarm_matches_baseline(alarm_doubles, load_alarm_config):
    """Tremor.run_alarm() representative behavior matches its frozen baseline."""
    run_and_compare("Tremor_representative", alarm_doubles, load_alarm_config)
