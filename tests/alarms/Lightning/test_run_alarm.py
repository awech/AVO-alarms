"""Integration test: Lightning ``run_alarm()`` end to end vs frozen baseline.

Drives the Lightning alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* representative - download returns None -> Volcview-API error WARNING
* critical       - recorded proximal strokes -> CRITICAL send with event-id list
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize("name", ["Lightning_representative", "Lightning_critical"])
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Lightning.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
