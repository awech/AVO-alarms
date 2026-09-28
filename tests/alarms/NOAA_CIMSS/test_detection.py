"""Unit tests for ``volc_alarms.alarms.NOAA_CIMSS.detection``.

These call the CIMSS parsing/filtering helpers directly with crafted DataFrames
and small HTML snippets. No network is used (``download_cimss_vv_api`` /
``scrape_cimss_alert`` / ``get_cimss_image`` do HTTP and are covered via the
integration path).

Covered:
* resolve_ignore_column  — per-type column preference, NOAA fallback, None
* format_cimss_dataframe — drop empty urls, derive NOAA_id, parse+sort time
* check_ignore_volcano   — keep all when no NOAA column exists in the list
* get_timestamp / get_latitude — small BeautifulSoup field extractors
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from obspy import UTCDateTime

from volc_alarms.alarms.NOAA_CIMSS.detection import (
    check_ignore_volcano,
    format_cimss_dataframe,
    get_latitude,
    get_timestamp,
    resolve_ignore_column,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# resolve_ignore_column
# ---------------------------------------------------------------------------
def test_resolve_ignore_column_prefers_specific_type_column():
    """resolve_ignore_column returns the granular per-type column when present."""
    cols = ["Name", "NOAA Ash", "NOAA"]
    assert resolve_ignore_column("ash", cols) == "NOAA Ash"


def test_resolve_ignore_column_falls_back_to_generic_noaa():
    """resolve_ignore_column falls back to the generic 'NOAA' column."""
    cols = ["Name", "NOAA"]
    assert resolve_ignore_column("hot", cols) == "NOAA"


def test_resolve_ignore_column_none_when_no_relevant_column():
    """resolve_ignore_column returns None when no NOAA column exists."""
    assert resolve_ignore_column("ash", ["Name", "Latitude"]) is None


# ---------------------------------------------------------------------------
# format_cimss_dataframe
# ---------------------------------------------------------------------------
def test_format_cimss_dataframe_derives_id_and_drops_empty_urls():
    """format_cimss_dataframe drops empty alert_urls, extracts NOAA_id, parses time."""
    cimss_df = pd.DataFrame(
        {
            "alert_url": ["https://x/alerts/101", "", "https://x/alerts/102"],
            "object_date_time": [
                "2025-01-01T00:00:00",
                "2025-01-01T00:05:00",
                "2025-01-01T00:10:00",
            ],
        }
    )
    out = format_cimss_dataframe(cimss_df, SimpleNamespace(), UTCDateTime("2025-01-01"))

    # The empty-url row is dropped; ids parsed from the url tail.
    assert list(out["NOAA_id"]) == [101, 102]
    # Sorted ascending by parsed time.
    assert list(out["time"]) == sorted(out["time"])


# ---------------------------------------------------------------------------
# check_ignore_volcano
# ---------------------------------------------------------------------------
def test_check_ignore_volcano_keeps_all_when_no_noaa_column():
    """check_ignore_volcano keeps every row when the volcano list has no NOAA column."""
    # The bundled test volcano list has only Name/Latitude/Longitude.
    cimss_df = pd.DataFrame(
        {"v_name": ["Pavlof", "Cleveland"], "alert_type": ["ash", "hot"]}
    )
    out = check_ignore_volcano(cimss_df)
    assert out["keep"].all()


# ---------------------------------------------------------------------------
# get_timestamp / get_latitude (BeautifulSoup field extractors)
# ---------------------------------------------------------------------------
def test_get_timestamp_extracts_utc_datetime_cell():
    """get_timestamp reads the value cell following a 'Date/Time' label."""
    from bs4 import BeautifulSoup

    html = "<table><tr><td>Date/Time</td><td>2025-01-01 00:00 UTC</td></tr></table>"
    soup = BeautifulSoup(html, "html.parser")
    assert get_timestamp(soup).strip() == "2025-01-01 00:00"


def test_get_latitude_parses_radiative_center_coordinates():
    """get_latitude parses the lat/lon pair following a 'Radiative Center' label."""
    from bs4 import BeautifulSoup

    html = (
        "<table><tr><td>Radiative Center</td>"
        "<td>55.42, -161.89</td></tr></table>"
    )
    soup = BeautifulSoup(html, "html.parser")
    lat, lon = get_latitude(soup)
    assert lat == pytest.approx(55.42)
    assert lon == pytest.approx(-161.89)
