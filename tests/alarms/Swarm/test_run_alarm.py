"""Integration test: Swarm ``run_alarm()`` end to end vs frozen baseline.

Drives the Swarm alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* critical             - recorded Makushin swarm -> CRITICAL detection + send
* multi_param          - one sequence caught by both param sets -> single deduped send
* simultaneous_swarms  - two clusters at different volcanoes -> two CRITICAL sends
* continuation         - new events extend a prior swarm (from the DB) -> WARNING
* no_swarm             - events near a volcano but too few to cluster -> OK
* not_near_volcano     - events far from any volcano -> OK
* fdsn_error           - download returns None -> FDSN connection error WARNING

The critical/multi_param/simultaneous/continuation scenarios run the real
get_swarms / compare_swarms / check_swarm_continue clustering; the figure render
is unit-tested in test_figure.py.
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Swarm-critical",
        "Swarm-multi_param",
        "Swarm-simultaneous_swarms",
        "Swarm-continuation",
        "Swarm-no_swarm",
        "Swarm-not_near_volcano",
        "Swarm-fdsn_error",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Swarm.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
