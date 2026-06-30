"""Utilities for capturing and persisting golden behavior baselines.

After a scenario drives run_alarm() offline, these helpers snapshot the
observable behavior into a deterministic, JSON-serializable dict:

- detection_state: the Icinga state (OK / WARNING / CRITICAL)
- icinga: all Icinga heartbeat calls (state + message)
- post_mattermost: all Mattermost posts (subject, body, flags)
- send_alert: all email alerts (alarm_name, subject, body)
- record_send: DB writes (alarm_id, volcano, event_id, time)
- os_remove: file cleanup calls (normalized paths)
- call_order: full chronological call sequence

The snapshots are persisted as JSON in tests/alarms/baselines/ and compared
on subsequent test runs to detect unintended behavior changes.

Determinism is guaranteed by:
- Fixed T0 (no wall-clock dependency)
- FROMCRON unset (no sleeps)
- All external I/O replaced by test doubles
- Path normalization (placeholder figure → token)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.alarms.fakes import AlarmDoubles, CallRecorder, FakeAlarmDB

# Frozen baselines live next to this module.
BASELINES_DIR = Path(__file__).resolve().parent / "baselines"

# A single fixed processing time shared by every scenario. Using a constant T0
# (rather than "now") keeps record_send's processed-time and every timestamped
# state message reproducible across regenerations.
from obspy import UTCDateTime  # noqa: E402

T0 = UTCDateTime("2025-01-01T00:00:00")

# Stable placeholder substituted for the placeholder figure path so snapshots do
# not depend on an absolute/relative filesystem location.
FIGURE_TOKEN = "<FIGURE>"


def _norm_path(path: Any, placeholder: Path) -> str:
    """Map the placeholder figure path (or anything derived from it) to a token."""
    s = str(path)
    if s == str(placeholder):
        return FIGURE_TOKEN
    # Renamed figures (Magnitude/Swarm) keep the tmp_files dir; collapse those too.
    if s.startswith(str(placeholder.parent) + "/"):
        return f"{FIGURE_TOKEN}:{Path(s).name}"
    return s


def _norm_time(value: Any) -> Any:
    """Render UTCDateTime / timestamp-ish values as a stable ISO string."""
    if isinstance(value, UTCDateTime):
        return value.isoformat()
    return value


def _norm_record(row: dict) -> dict:
    """Normalize one FakeAlarmDB.record_send row to the four baseline fields."""
    return {
        "alarm_id": row.get("alarm_id"),
        "volcano": row.get("volcano"),
        "event_id": row.get("event_id"),
        "process_time": _norm_time(row.get("process_time")),
        "test": bool(row.get("test", False)),
    }


def snapshot(recorder: CallRecorder, db: FakeAlarmDB, placeholder: Path) -> dict:
    """Build the deterministic ``Behavior_Baseline`` dict for one run_alarm call.

    Reads only the doubled-call timeline (``recorder``) and the in-memory send
    store (``db``) -- never any live state -- so the result is JSON-serializable
    and reproducible.
    """
    icinga = [
        {
            "state": c.args[1] if len(c.args) > 1 else None,
            "state_message": c.args[2] if len(c.args) > 2 else None,
            "send": c.kwargs.get("send"),
        }
        for c in recorder.of("icinga")
    ]

    post_mattermost = [
        {
            "subject": c.args[1] if len(c.args) > 1 else None,
            "body": c.args[2] if len(c.args) > 2 else None,
            "send": c.kwargs.get("send"),
            "test": c.kwargs.get("test"),
            "volcano": c.kwargs.get("volcano"),
            "channel_ids": c.kwargs.get("channel_ids"),
        }
        for c in recorder.of("post_mattermost")
    ]

    send_alert = [
        {
            "alarm_name": c.args[0] if len(c.args) > 0 else None,
            "subject": c.args[1] if len(c.args) > 1 else None,
            "body": c.args[2] if len(c.args) > 2 else None,
            "test": c.kwargs.get("test"),
        }
        for c in recorder.of("send_alert")
    ]

    record_send = [_norm_record(r) for r in db.records]
    os_remove = [_norm_path(c.args[0], placeholder) for c in recorder.of("os.remove")]

    # The resolved detection state is what the final Icinga heartbeat carries.
    detection_state = icinga[-1]["state"] if icinga else None

    return {
        "detection_state": detection_state,
        "icinga": icinga,
        "post_mattermost": post_mattermost,
        "send_alert": send_alert,
        "record_send": record_send,
        "os_remove": os_remove,
        "call_order": recorder.names(),
    }


def capture(doubles: AlarmDoubles) -> dict:
    """Snapshot the behavior recorded on ``doubles`` after a run_alarm call."""
    return snapshot(doubles.recorder, doubles.db, doubles.placeholder_figure)


def baseline_path(name: str) -> Path:
    return BASELINES_DIR / f"{name}.json"


def load_baseline(name: str) -> dict:
    with baseline_path(name).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def freeze_baseline(name: str, data: dict) -> Path:
    """Persist ``data`` as a frozen JSON fixture and return its path."""
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = baseline_path(name)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return path
