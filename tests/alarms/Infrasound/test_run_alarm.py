"""Integration test: Infrasound ``run_alarm()`` end to end vs frozen baseline.

Drives the Infrasound alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline. All four scenarios replay
the same recorded KENI array event, differing only in a small config tweak that
steers run_alarm down each outcome branch.

Scenarios:
* not_enough_channels - only 2 live channels -> "Not enough channels!" WARNING
* below_amplitude     - high min_pa -> "not enough channels exceeding amplitude" OK
* wrong_backazimuth   - coherent wave, no target accepts its azimuth -> no detection
* critical            - real arrival at Fourpeaked/Katmai -> CRITICAL + full send
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Infrasound-not_enough_channels",
        "Infrasound-below_amplitude",
        "Infrasound-wrong_backazimuth",
        "Infrasound-critical",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Infrasound.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
