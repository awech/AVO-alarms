"""Unit tests for ``volc_alarms.utils.alarm_flow``.

These cover the two shared control-flow helpers with the external steps
(can_send / record_send / post_mattermost / send_alert / icinga / os.remove)
locally monkeypatched. No network, DB, email, or matplotlib is involved.

Covered:
* apply_cron_latency_backup — no-cron passthrough, cron sleep (<30), cron backup (>=30)
* run_send_sequence         — rate-limit skip (+ resume-time log), full ordered send,
                              last-alert-before-rate-limit annotation, figure-factory
                              and post_mattermost exception handling, send_email=False,
                              and can_send/record/mm kwargs forwarding
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


# ---------------------------------------------------------------------------
# run_send_sequence — additional branches
# ---------------------------------------------------------------------------
def test_run_send_sequence_rate_limited_logs_resume_time(wired):
    """The rate-limit skip path consults next_send_after when a resume time exists (lines 86-87)."""
    from datetime import datetime, timedelta, timezone

    wired["can_send"] = False
    # next_send_after returns a timezone-aware python datetime.
    wired["next_send_after"] = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=30)

    out = alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
    )

    assert "next_send_after" in wired["calls"]
    assert out.endswith("(alarm skipped due to rate limit)")
    assert "post_mattermost" not in wired["calls"]


def test_run_send_sequence_annotates_last_alert_before_rate_limit(wired, monkeypatch):
    """When next_send_after is set, the message gets the alert-limit warning (lines 107-115)."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("TIMEZONE", "US/Alaska")
    # next_send_after returns a timezone-aware python datetime (not UTCDateTime);
    # run_send_sequence calls .astimezone()/.strftime() on it.
    wired["next_send_after"] = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=1)

    captured = {}

    def _post(config, subject, message, attachment=None, send=True, test=False, **kw):
        captured["message"] = message
        wired["calls"].append("post_mattermost")
        return "mattermost://test/post-id"

    monkeypatch.setattr(alarm_flow.messaging, "post_mattermost", _post)

    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
    )

    assert "Alert limit reached" in captured["message"]
    assert "UTC" in captured["message"]


def test_run_send_sequence_handles_figure_factory_exception(wired, monkeypatch):
    """A figure_factory error is swallowed; the send proceeds with no attachment (lines 95-99)."""
    def _boom():
        raise RuntimeError("matplotlib exploded")

    captured = {}

    def _post(config, subject, message, attachment=None, send=True, test=False, **kw):
        captured["attachment"] = attachment
        wired["calls"].append("post_mattermost")
        return "mattermost://test/post-id"

    monkeypatch.setattr(alarm_flow.messaging, "post_mattermost", _post)

    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=_boom,
        message_factory=lambda: ("subj", "body"),
    )

    # figure failed -> attachment is None, but the sequence still posts/records.
    assert captured["attachment"] is None
    assert "record_send" in wired["calls"]
    # No cleanup since there was no file.
    assert "os.remove" not in wired["calls"]


def test_run_send_sequence_handles_post_mattermost_exception(wired, monkeypatch):
    """A post_mattermost error is swallowed; email/record/cleanup/icinga still run (lines 127-130)."""
    def _boom(*a, **k):
        wired["calls"].append("post_mattermost")
        raise RuntimeError("mattermost down")

    monkeypatch.setattr(alarm_flow.messaging, "post_mattermost", _boom)

    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
    )

    # Despite the post failure, the rest of the sequence completed.
    assert "send_alert" in wired["calls"]
    assert "record_send" in wired["calls"]
    assert "os.remove" in wired["calls"]
    assert wired["calls"][-1] == "icinga"


def test_run_send_sequence_skips_email_when_send_email_false(wired):
    """run_send_sequence does not call send_alert when send_email=False."""
    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
        send_email=False,
    )

    assert "send_alert" not in wired["calls"]
    assert "post_mattermost" in wired["calls"]
    assert "record_send" in wired["calls"]
    assert wired["calls"][-1] == "icinga"


def test_run_send_sequence_forwards_kwargs_to_steps(wired, monkeypatch):
    """can_send_kwargs / record_kwargs / mm_kwargs are forwarded to their steps."""
    seen = {}

    def _can_send(config, T0=None, test=False, **kw):
        seen["can_send"] = kw
        wired["calls"].append("can_send")
        return True

    def _record_send(config, T0, test=False, **kw):
        seen["record"] = kw
        wired["calls"].append("record_send")

    def _post(config, subject, message, attachment=None, send=True, test=False, **kw):
        seen["mm"] = kw
        wired["calls"].append("post_mattermost")
        return "mattermost://test/post-id"

    monkeypatch.setattr(alarm_flow.alarming, "can_send", _can_send)
    monkeypatch.setattr(alarm_flow.alarming, "record_send", _record_send)
    monkeypatch.setattr(alarm_flow.messaging, "post_mattermost", _post)

    alarm_flow.run_send_sequence(
        _config(),
        T0,
        "CRITICAL",
        "state msg",
        figure_factory=lambda: "fig.jpg",
        message_factory=lambda: ("subj", "body"),
        can_send_kwargs={"volcano": "Pavlof"},
        record_kwargs={"volcano": "Pavlof", "event_id": "evt-1"},
        mm_kwargs={"volcano": "Pavlof"},
    )

    assert seen["can_send"] == {"volcano": "Pavlof"}
    assert seen["record"] == {"volcano": "Pavlof", "event_id": "evt-1"}
    assert seen["mm"] == {"volcano": "Pavlof"}
