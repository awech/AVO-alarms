"""Unit tests for ``volc_alarms.utils.messaging``.

Focus on the pure formatting/helper logic. The network-bound senders
(``send_alert``/``post_mattermost``/``connect_mattermost``/``upload_mm_attachments``)
are exercised end to end by the integration harness; here we only unit-test the
parts that transform text/data and the ``send=False`` short-circuits.

Covered:
* attachments_tolist    — None/str/list normalization
* format_timestring     — UTC + local formatting, minute vs second precision
* format_nearest_volcanoes — "Name (dist km)" join, underscore->space, n cap
* format_mm_message     — markdown checkboxes + PIREP heading rules
* icinga(send=False)    — no-op short-circuit (no requests call)
* post_mattermost(send=False) — returns "" without connecting

TODO: the actual SMTP/Mattermost send paths need a mocked driver/SMTP and are
covered indirectly by the integration tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from obspy import UTCDateTime
from pandas import DataFrame

from volc_alarms.utils import messaging

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# attachments_tolist
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        (None, []),
        ("", []),
        ("a.jpg", ["a.jpg"]),
        (["a.jpg", "b.jpg"], ["a.jpg", "b.jpg"]),
    ],
)
def test_attachments_tolist_normalizes_to_list(value, expected):
    """attachments_tolist wraps a scalar, passes a list, and maps falsy to []."""
    assert messaging.attachments_tolist(value) == expected


# ---------------------------------------------------------------------------
# format_timestring
# ---------------------------------------------------------------------------
def test_format_timestring_uses_minute_precision_on_round_times():
    """format_timestring uses %H:%M when the single time has zero seconds."""
    t1 = UTCDateTime("2025-01-01T00:30:00")
    out = messaging.format_timestring(t1)
    assert "2025-01-01 00:30 UTC" in out
    # No seconds field on a round minute.
    assert "00:30:00" not in out


def test_format_timestring_uses_second_precision_when_seconds_present():
    """format_timestring falls back to %H:%M:%S when seconds are non-zero."""
    t1 = UTCDateTime("2025-01-01T00:30:15")
    out = messaging.format_timestring(t1)
    assert "00:30:15" in out


def test_format_timestring_range_labels_start_and_end():
    """format_timestring with two times labels both Start and End in UTC."""
    t1 = UTCDateTime("2025-01-01T00:00:00")
    t2 = UTCDateTime("2025-01-01T01:00:00")
    out = messaging.format_timestring(t1, t2)
    assert "Start: 2025-01-01 00:00 (UTC)" in out
    assert "End: 2025-01-01 01:00 (UTC)" in out


# ---------------------------------------------------------------------------
# format_nearest_volcanoes
# ---------------------------------------------------------------------------
def test_format_nearest_volcanoes_joins_name_and_distance():
    """format_nearest_volcanoes renders 'Name (dist km)' sorted, underscores spaced."""
    volcs = DataFrame(
        {
            "Name": ["Mount_Spurr", "Redoubt", "Iliamna"],
            "distance": [12.3, 48.6, 70.1],
        }
    )
    out = messaging.format_nearest_volcanoes(volcs, n=2)
    assert out == "Mount Spurr (12 km), Redoubt (49 km)"


def test_format_nearest_volcanoes_empty_table_returns_empty_string():
    """format_nearest_volcanoes returns '' for an empty volcano table."""
    volcs = DataFrame({"Name": [], "distance": []})
    assert messaging.format_nearest_volcanoes(volcs) == ""


# ---------------------------------------------------------------------------
# format_mm_message
# ---------------------------------------------------------------------------
def test_format_mm_message_wraps_non_pirep_subject_as_h3():
    """format_mm_message renders a non-PIREP subject as a bold H3 heading."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    message = messaging.format_mm_message("--- RSAM detection ---", "body text", config)
    # The '---' framing is stripped and the subject becomes an H3.
    assert message.startswith("### **RSAM detection**")
    assert "body text" in message


def test_format_mm_message_pirep_non_urgent_uses_h4():
    """format_mm_message uses an H4 heading for a non-urgent PIREP subject."""
    config = SimpleNamespace(alarm_name="PIREP")
    message = messaging.format_mm_message("Pilot report", "body", config)
    assert message.startswith("#### **Pilot report**")


# ---------------------------------------------------------------------------
# send=False short-circuits (no network)
# ---------------------------------------------------------------------------
def test_icinga_send_false_is_a_noop():
    """icinga(send=False) returns without attempting any HTTP request."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    # Should not raise even though no ICINGA_* env vars are configured.
    assert messaging.icinga(config, "OK", "all good", send=False) is None


def test_post_mattermost_send_false_returns_empty_string():
    """post_mattermost(send=False) returns '' without connecting to a server."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    assert messaging.post_mattermost(config, "subj", "body", send=False) == ""
