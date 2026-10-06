"""Unit tests for ``volc_alarms.alarms.Pilot_Report.detection``.

These call the PIREP text-parsing helpers directly with crafted report strings /
DataFrames. No network or shapefile I/O is used (``download_pilot_reports`` /
``pirep_archive_to_dataframe`` hit the API and unpack a shapefile; those are
covered via the integration path).

Covered:
* check_volcano_mention — trigger flag from ash/volcano keywords and /SK,/RM VA
* check_volcano_mention — false-positive guards (VAR, PREVAIL, CORDOVA, ...)
* get_height_text       — numeric flight level formatting + UNKNOWN fallback
* get_pilot_remark      — extract and capitalize the RM remark field
"""

from __future__ import annotations

import pandas as pd
import pytest

from volc_alarms.alarms.Pilot_Report.detection import (
    check_volcano_mention,
    get_height_text,
    get_pilot_remark,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# check_volcano_mention
# ---------------------------------------------------------------------------
def test_check_volcano_mention_triggers_on_ash_keyword():
    """check_volcano_mention flags a report that mentions ASH/volcanic keywords."""
    df = pd.DataFrame({"REPORT": ["UA /OV ABC /RM OBSERVED ASH PLUME TO FL300"]})
    out = check_volcano_mention(df)
    assert out.loc[0, "trigger"] is True or out.loc[0, "trigger"]


def test_check_volcano_mention_does_not_trigger_on_false_positive_words():
    """check_volcano_mention ignores 'VA' substrings inside benign words."""
    df = pd.DataFrame({"REPORT": ["UA /OV CORDOVA /RM PREVAIL VISIBILITY AVAIL"]})
    out = check_volcano_mention(df)
    assert not out.loc[0, "trigger"]


def test_check_volcano_mention_triggers_on_va_in_sky_condition_field():
    """check_volcano_mention flags 'VA' appearing in the /SK sky-condition field."""
    df = pd.DataFrame({"REPORT": ["UA /OV XYZ /SK VA LYR /TB NEG"]})
    out = check_volcano_mention(df)
    assert out.loc[0, "trigger"]


# ---------------------------------------------------------------------------
# get_height_text
# ---------------------------------------------------------------------------
def test_get_height_text_formats_numeric_flight_level():
    """get_height_text renders a numeric flight level with thousands separators."""
    assert get_height_text(30000) == "Flight level: 30,000 feet asl"


def test_get_height_text_unknown_when_not_numeric():
    """get_height_text falls back to UNKNOWN when the level can't be formatted."""
    assert get_height_text("bad") == "Flight level: UNKNOWN"


# ---------------------------------------------------------------------------
# get_pilot_remark
# ---------------------------------------------------------------------------
def test_get_pilot_remark_extracts_and_capitalizes_rm_field():
    """get_pilot_remark returns the capitalized text of the /RM remark field."""
    remark = get_pilot_remark("UA /OV ABC /FL300 /RM ash observed to the east")
    assert remark == "Ash observed to the east"


def test_get_pilot_remark_returns_na_when_absent():
    """get_pilot_remark returns 'NA' when the report has no RM field."""
    assert get_pilot_remark("UA /OV ABC /FL300 /TB NEG") == "NA"
