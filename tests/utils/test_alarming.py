"""Unit tests for ``volc_alarms.utils.alarming``.

These exercise the alarm-history/rate-limiting logic against a throwaway sqlite
database (``DB_FILE`` pointed at a tmp file per test). No network, email, or
Mattermost is involved — only the local sqlite the module already uses.

Covered:
* iso_utc                — UTC ISO-8601 with 'Z' suffix
* resolve_table_name     — test/prod table selection per table kind
* record_send / already_processed — write a send, then detect it
* record_send            — volcano_name on config overrides the volcano arg
* can_send               — rate-limit on/off and saturation
* next_send_after        — earliest re-allow time once saturated
* check_new_event_ids    — (new_count, existing_count) accounting
* record_swarm_event_ids — swarm-table INSERT OR IGNORE de-dup

TODO: list_all_alarm_ids / filtered_list / list_alarm_entries / remove_alarm_ids
are operator CLI helpers (mostly print/formatting) — covered lightly or left for
a later pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from obspy import UTCDateTime

from volc_alarms.utils import alarming

pytestmark = pytest.mark.unit


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point DB_FILE at a fresh sqlite file for the duration of the test."""
    db_file = tmp_path / "alarms_test.db"
    monkeypatch.setenv("DB_FILE", str(db_file))
    return db_file


def _config(alarm_name="Test RSAM", **extra):
    """A minimal config object; extra kwargs add optional rate-limit knobs."""
    return SimpleNamespace(alarm_name=alarm_name, **extra)


# ---------------------------------------------------------------------------
# iso_utc
# ---------------------------------------------------------------------------
def test_iso_utc_appends_z_suffix_and_normalizes_to_utc():
    """iso_utc renders a tz-aware datetime as second-precision ISO-8601 with 'Z'."""
    dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert alarming.iso_utc(dt) == "2025-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# resolve_table_name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "test, table, expected",
    [
        (False, None, "sent_events"),
        (True, None, "test_sent_events"),
        (False, "swarm", "swarm_table"),
        (True, "swarm", "test_swarm_table"),
        (False, "tremor", "tremor_table"),
        (True, "tremor", "test_tremor_table"),
    ],
)
def test_resolve_table_name_selects_expected_table(test, table, expected):
    """resolve_table_name picks the prod/test table for each table kind."""
    assert alarming.resolve_table_name(test, table=table) == expected


# ---------------------------------------------------------------------------
# record_send + already_processed
# ---------------------------------------------------------------------------
def test_record_send_then_already_processed_detects_event(temp_db):
    """A recorded send is subsequently reported as already-processed for its event."""
    config = _config(alarm_name="Pavlof RSAM")
    T0 = UTCDateTime("2025-01-01T00:00:00")

    assert alarming.already_processed(config, "evt-1", test=True) is False
    alarming.record_send(config, T0, volcano="Pavlof", event_id="evt-1", test=True)
    assert alarming.already_processed(config, "evt-1", test=True) is True
    # A different event id is still unseen.
    assert alarming.already_processed(config, "evt-2", test=True) is False


def test_record_send_uses_volcano_name_from_config(temp_db):
    """record_send overrides the volcano arg with config.volcano_name when present."""
    config = _config(alarm_name="Pavlof RSAM", volcano_name="Pavlof")
    T0 = UTCDateTime("2025-01-01T00:00:00")

    # Pass a different volcano arg; config.volcano_name should win.
    alarming.record_send(config, T0, volcano="SomewhereElse", event_id="evt-1", test=True)

    new_count, existing_count = alarming.check_new_event_ids(["evt-1"], test=True)
    assert (new_count, existing_count) == (0, 1)


def test_record_send_expands_event_id_list(temp_db):
    """record_send writes one row per event id when given a list."""
    config = _config(alarm_name="Lightning")
    T0 = UTCDateTime("2025-01-01T00:00:00")

    alarming.record_send(config, T0, event_id=["L1", "L2", "L3"], test=True)

    new_count, existing_count = alarming.check_new_event_ids(["L1", "L2", "L3"], test=True)
    assert (new_count, existing_count) == (0, 3)


# ---------------------------------------------------------------------------
# can_send (rate-limiting)
# ---------------------------------------------------------------------------
def test_can_send_returns_true_when_rate_limit_not_configured(temp_db):
    """can_send is always True when alert_memory/max_alerts are not both set."""
    config = _config()  # no alert_memory / max_alerts
    T0 = UTCDateTime("2025-01-01T00:00:00")
    assert alarming.can_send(config, T0=T0, test=True) is True


def test_can_send_blocks_once_max_alerts_reached_within_memory_window(temp_db):
    """can_send returns False once max_alerts sends land inside alert_memory."""
    config = _config(alarm_name="Chatty", alert_memory=3600, max_alerts=2)
    T0 = UTCDateTime("2025-01-01T00:00:00")

    # No sends yet -> allowed.
    assert alarming.can_send(config, T0=T0, test=True) is True

    # Two sends within the last hour -> now saturated.
    alarming.record_send(config, UTCDateTime("2025-01-01T00:30:00"), event_id="a", test=True)
    alarming.record_send(config, UTCDateTime("2025-01-01T00:45:00"), event_id="b", test=True)
    assert alarming.can_send(config, T0=UTCDateTime("2025-01-01T00:50:00"), test=True) is False


def test_can_send_ignores_sends_outside_memory_window(temp_db):
    """can_send only counts sends whose process_time is within alert_memory."""
    config = _config(alarm_name="Windowed", alert_memory=3600, max_alerts=1)

    # A send well before the window.
    alarming.record_send(config, UTCDateTime("2025-01-01T00:00:00"), event_id="old", test=True)
    # Query three hours later -> the old send is outside the 1h window.
    assert alarming.can_send(config, T0=UTCDateTime("2025-01-01T03:00:00"), test=True) is True


# ---------------------------------------------------------------------------
# next_send_after
# ---------------------------------------------------------------------------
def test_next_send_after_none_when_not_saturated(temp_db):
    """next_send_after returns None when this send would not reach max_alerts."""
    config = _config(alarm_name="Calm", alert_memory=3600, max_alerts=5)
    T0 = UTCDateTime("2025-01-01T01:00:00")
    assert alarming.next_send_after(config, T0=T0, test=True) is None


def test_next_send_after_returns_oldest_plus_memory_when_saturated(temp_db):
    """next_send_after returns oldest-in-window + alert_memory once saturated."""
    config = _config(alarm_name="Saturated", alert_memory=3600, max_alerts=1)
    alarming.record_send(config, UTCDateTime("2025-01-01T00:30:00"), event_id="a", test=True)

    result = alarming.next_send_after(config, T0=UTCDateTime("2025-01-01T00:45:00"), test=True)
    # oldest send 00:30 + 3600s memory = 01:30 UTC.
    assert result == datetime(2025, 1, 1, 1, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# check_new_event_ids
# ---------------------------------------------------------------------------
def test_check_new_event_ids_counts_new_and_existing(temp_db):
    """check_new_event_ids returns (new_count, existing_count) against the DB."""
    config = _config(alarm_name="Mixer")
    alarming.record_send(config, UTCDateTime("2025-01-01T00:00:00"), event_id="known", test=True)

    new_count, existing_count = alarming.check_new_event_ids(["known", "fresh"], test=True)
    assert (new_count, existing_count) == (1, 1)


def test_check_new_event_ids_empty_input_returns_zero_zero(temp_db):
    """check_new_event_ids short-circuits to (0, 0) when given no usable ids."""
    assert alarming.check_new_event_ids([None], test=True) == (0, 0)
    assert alarming.check_new_event_ids([], test=True) == (0, 0)


# ---------------------------------------------------------------------------
# record_swarm_event_ids
# ---------------------------------------------------------------------------
def test_record_swarm_event_ids_dedupes_on_event_id(temp_db):
    """record_swarm_event_ids inserts rows and ignores duplicate event ids."""
    df = pd.DataFrame(
        {
            "event_id": ["s1", "s2"],
            "time": pd.to_datetime(["2025-01-01 00:00:00", "2025-01-01 00:05:00"]),
            "latitude": [55.4, 55.5],
            "longitude": [-161.9, -162.0],
            "depth": [5.0, 6.0],
            "mag": [2.1, 2.4],
            "v_name": ["Pavlof", "Pavlof"],
        }
    )

    alarming.record_swarm_event_ids(df, test=True)
    # Re-recording the same ids must not create duplicates (INSERT OR IGNORE).
    alarming.record_swarm_event_ids(df, test=True)

    new_count, existing_count = alarming.check_new_event_ids(
        ["s1", "s2"], test=True, table="swarm"
    )
    assert (new_count, existing_count) == (0, 2)
