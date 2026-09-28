"""Unit tests for ``volc_alarms.alarms.Lightning.message.create_message``.

These build the Lightning alert text from crafted stroke DataFrames. No network
or rendering is involved (``format_timestring`` reads only the TIMEZONE env var,
set to UTC by the top-level conftest).

Covered:
* create_message — subject, new/total stroke counts, bearing/distance, data source
* create_message — singular vs plural "stroke(s)" wording
"""

from __future__ import annotations

import pandas as pd
import pytest

from volc_alarms.alarms.Lightning.message import create_message

pytestmark = pytest.mark.unit


def _strokes(n):
    """n proximal strokes near Pavlof from the Earth Networks (EN) source."""
    return pd.DataFrame(
        {
            "id": [f"L{i}" for i in range(n)],
            "time": pd.to_datetime(
                [pd.Timestamp("2025-01-01 00:00:00") + pd.Timedelta(minutes=i) for i in range(n)]
            ),
            "v_name": ["Pavlof"] * n,
            "v_distance": [5.0] * n,
            "api_vlat": [55.42] * n,
            "api_vlon": [-161.89] * n,
            "latitude": [55.40] * n,
            "longitude": [-161.80] * n,
            "dataSource": ["EN"] * n,
        }
    )


def test_create_message_reports_counts_bearing_and_source():
    """create_message includes new/total counts, distance+bearing, and the data source."""
    df_recent = _strokes(3)
    df_new = df_recent.iloc[1:]  # 2 new strokes

    subject, message = create_message(df_new, df_recent)

    assert subject == "--- Pavlof Lightning ---"
    assert "2 new strokes! (3 total)" in message
    assert "5 km" in message and "of Pavlof" in message
    # The 'EN' code is expanded to a friendly source name.
    assert "Data source: Earth Networks" in message


def test_create_message_uses_singular_wording_for_one_new_stroke():
    """create_message says 'stroke' (singular) when exactly one new stroke arrives."""
    df_recent = _strokes(1)
    _, message = create_message(df_recent, df_recent)
    assert "1 new stroke! (1 total)" in message
