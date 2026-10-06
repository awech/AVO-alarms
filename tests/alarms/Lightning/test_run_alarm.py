"""Integration test: Lightning ``run_alarm()`` end to end vs frozen baseline.

Drives the Lightning alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* critical         - real Edgecumbe storm, proximal first stroke -> CRITICAL + send
* distal           - real storm, all strokes distal -> WARNING, no send
* ignored_volcano  - proximal strokes at an ignored (N) volcano -> suppressed -> OK
* no_data          - API returns an empty list -> OK "No new strokes"
* api_error         - download returns None -> Volcview-API error WARNING
* all_seen         - proximal strokes but DB already saw every id -> OK, no re-alert

The first three replay a real pared API pull through the real download_lightning
parser (only curl is faked) and the normal find_nearest_volcano path.
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Lightning-critical",
        "Lightning-distal",
        "Lightning-ignored_volcano",
        "Lightning-no_data",
        "Lightning-api_error",
        "Lightning-all_seen",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Lightning.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
