"""Integration test: NOAA_CIMSS ``run_alarm()`` end to end vs frozen baseline.

Drives the NOAA_CIMSS alarm through the shared fakes harness and compares its
observable behavior against the frozen JSON baseline.

Scenarios:
* critical          - recorded Spurr ash alert (real API JSON + scraped HTML) ->
                      CRITICAL detection + send
* api_error         - download returns None -> Volcview-API error WARNING
* no_new_alerts     - alerts present but far from any volcano -> OK
* webpage_error     - near-volcano alert, but the alert page won't scrape -> WARNING
* already_processed - the recorded alert, already in the DB -> OK
* ignored_volcano   - an alert at a NOAA=N volcano (Tana) -> suppressed -> OK

The critical/webpage_error/already_processed scenarios run the real
download_cimss_vv_api (os.popen faked) and the real process_alert_soup over the
recorded alert HTML; the figure render is unit-tested in test_figure.py.
"""

from __future__ import annotations

import pytest

from tests._harness.compare import run_and_compare


@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "NOAA_CIMSS-critical",
        "NOAA_CIMSS-api_error",
        "NOAA_CIMSS-no_new_alerts",
        "NOAA_CIMSS-webpage_error",
        "NOAA_CIMSS-already_processed",
        "NOAA_CIMSS-ignored_volcano",
    ],
)
def test_run_alarm_matches_baseline(name, alarm_doubles, load_alarm_config):
    """NOAA_CIMSS.run_alarm() behavior matches its frozen baseline for each scenario."""
    run_and_compare(name, alarm_doubles, load_alarm_config)
