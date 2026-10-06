"""Integration test: VAA ``run_alarm()`` end to end vs frozen baseline.

Drives the VAA alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* critical          - recorded Sheveluch eruption VAA -> CRITICAL detection + send
* webpage_error     - download returns None -> webpage error WARNING
* no_advisories     - empty advisory list -> "No new Volcanic Ash Advisories" OK
* already_processed - the recorded VAA, already in the DB -> OK

The critical/already_processed scenarios feed the recorded advisory text through
the real process_vaa_id parse; the figure render is unit-tested in test_figure.py.
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "VAA-critical",
        "VAA-webpage_error",
        "VAA-no_advisories",
        "VAA-already_processed",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """VAA.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
