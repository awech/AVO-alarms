"""Unit tests for ``volc_alarms.utils.alarm_flow``.

These cover the two shared control-flow helpers with the external steps
(can_send / record_send / post_mattermost / send_alert / icinga / os.remove)
locally monkeypatched. No network, DB, email, or matplotlib is involved.

Covered:
* apply_cron_latency_backup — no-cron passthrough, cron sleep (<30), cron backup (>=30)
* run_send_sequence         — rate-limit skip path, and the full ordered send path
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from obspy import UTCDateTime

from volc_alarms.utils import alarm_flow

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2025-01-01T00:00:00")


# ---------------------------------------------------------------------------
# apply_cron_latency_backup
# ---------------------------------------------------------------------------
def test_apply_cron_latency_backup_noop_when_not_cron(monkeypatch):
    """apply_cron_latency_backup returns T0 unchanged and never sleeps off-cron."""
    monkeypatch.delenv("FROMCRON", raising=False)
    slept = []
    monkeypatch.setattr(alarm_flow.time, "sleep", lambda s: slept.append(s))

    config = SimpleNamespace(latency=45)
    out = alarm_flow.apply_cron_latency_backup(config, T0)

    assert out == T0
    assert slept == []


def test_apply_cron_latency_backup_sleeps_for_low_latency_on_cron(monkeypatch):
    """On cron with latency < 30, it sleeps latency+extra and returns T0 unchanged."""
    monkeypatch.setenv("FROMCRON", "yep")
    slept = []
    monkeypatch.setattr(alarm_flow.time, "sleep", lambda s: slept.append(s))

    config = SimpleNamespace(latency=10)
    out = alarm_flow.apply_cron_latency_backup(config, T0, extra_sleep=2.0)

    assert out == T0
    assert slept == [12.0]


def test_apply_cron_latency_backup_backs_up_time_for_high_latency_on_cron(monkeypatch):
    """On cron with latency >= 30, it backs T0 up to the minute mark and does not sleep."""
    monkeypatch.setenv("FROMCRON", "yep")
    slept = []
    monkeypatch.setattr(alarm_flow.time, "sleep", lambda s: slept.append(s))

    config = SimpleNamespace(latency=90)  # ceil(90/60)*60 = 120s back-up
    out = alarm_flow.apply_cron_latency_backup(config, T0)

    assert out == T0 - 120
    assert slept == []


# ---------------------------------------------------------------------------
# run_send_sequence
# ---------------------------------------------------------------------------
@pytest.fixture
def wired(monkeypatch):
    """Monkeypatch alarm_flow's external steps and record their call order.

    Returns a dict with the ordered ``calls`` list plus toggles for can_send and
    next_send_after so a test can drive either the skip or the full-send path.
    """
    state = {
        "calls": [],
        "can_send": True,
        "next_send_after": None,
    }

    def rec(name):
        def _fn(*args, **kwargs):
            state["calls"].append(name)
            if name == "can_send":
                return state["can_send"]
            if name == "next_send_after":
                return state["next_send_after"]
            if name == "post_mattermost":
                return "mattermost://test/post-id"
            return None

        return _fn

    monkeypatch.setattr(alarm_flow.alarming, "can_send", rec("can_send"))
    monkeypatch.setattr(alarm_flow.alarming, "next_send_after", rec("next_send_after"))
    monkeypatch.setattr(alarm_flow.alarming, "record_send", rec("record_send"))
    monkeypatch.setattr(alarm_flow.messaging, "post_mattermost", rec("post_mattermost"))
    monkeypatch.setattr(alarm_flow.messaging, "send_alert", rec("send_alert"))
    monkeypatch.setattr(alarm_flow.messaging, "icinga", rec("icinga"))
    monkeypatch.setattr(alarm_flow.os, "remove", rec("os.remove"))
    return state


def _config():
    return SimpleNamespace(
        alarm_name="Pavlof RSAM",
        max_alerts=3,
        alert_memory=3600,
    )


def test_run_send_sequence_rate_limited_skips_send_but_heartbeats(wired):
    """When can_send is False, run_send_sequence skips the send but still heartbeats icinga."""
    wired["can_send"] = False

    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
    )

    # No figure/message/post/record; icinga still called.
    assert "post_mattermost" not in wired["calls"]
    assert "record_send" not in wired["calls"]
    assert "os.remove" not in wired["calls"]
    assert wired["calls"][-1] == "icinga"


def test_run_send_sequence_full_path_calls_steps_in_order(wired):
    """The full send path posts, emails, records, cleans up, then heartbeats — in order."""
    calls = wired["calls"]

    result = alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
    )

    # can_send precedes post; record precedes cleanup; icinga is last.
    assert calls.index("can_send") < calls.index("post_mattermost")
    assert calls.index("post_mattermost") < calls.index("send_alert")
    assert calls.index("send_alert") < calls.index("record_send")
    assert calls.index("record_send") < calls.index("os.remove")
    assert calls[-1] == "icinga"
    assert result == "state msg"
