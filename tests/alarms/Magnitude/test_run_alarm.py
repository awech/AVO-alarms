"""Integration test: Magnitude ``run_alarm()`` end to end vs frozen baseline.

Drives the Magnitude alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* representative    - empty FDSN catalog -> "No new earthquakes" OK
* critical          - recorded M3.25 Denison event -> CRITICAL detection + send
* fdsn_error        - download returns None -> "FDSN connection error" WARNING
* not_near_volcano  - a quake far from any volcano -> "No new earthquakes" OK
* already_processed - the recorded event, already in the DB -> "Old event detected" OK

The critical/already_processed scenarios feed the recorded CSV + QuakeML through
the real detection + message path (the figure render is unit-tested in
test_figure.py).
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "Magnitude-representative",
        "Magnitude-critical",
        "Magnitude-fdsn_error",
        "Magnitude-not_near_volcano",
        "Magnitude-already_processed",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """Magnitude.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
