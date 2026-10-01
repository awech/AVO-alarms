"""Unit tests for ``volc_alarms.alarms.Swarm.detection``.

These call the swarm clustering/dedup helpers directly with crafted earthquake
DataFrames and a minimal config. No network is used (``build_download_url`` just
formats a URL; the FDSN fetch is covered via the integration path).

Covered:
* build_download_url    — assembles the FDSN CSV query from T0/config
* compare_swarms        — drops duplicate and overlapping swarm groups
* get_swarms            — DBSCAN clusters space+time-adjacent events into groups
* check_swarm_continue  — returns only the new events extending a prior swarm
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from obspy import UTCDateTime

from volc_alarms.alarms.Swarm.detection import (
    build_download_url,
    check_swarm_continue,
    compare_swarms,
    get_swarms,
)

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2025-01-01T01:00:00")


def _swarm_config():
    """A single DBSCAN parameter set that clusters nearby, recent events."""
    return SimpleNamespace(
        DURATION=3600,
        maxdep=50,
        swarm_parameters=[
            {
                "name": "shallow",
                "max_evt_time": 3600,
                "max_evt_distance": 10.0,
                "min_num_evt": 3,
            }
        ],
    )


def _events(n, base_lat=55.40, spread=0.001, start="2025-01-01 00:30:00", step_s=60):
    """n tightly-clustered events near one point within the look-back window."""
    times = pd.to_datetime(
        [pd.Timestamp(start) + pd.Timedelta(seconds=i * step_s) for i in range(n)]
    )
    # Real run_alarm data carries only 'event_id' and 'time' (the FDSN 'id' is
    # renamed by the downloader; there is no 'id'/'Time'). Match that so the
    # tests guard the real column names compare_swarms/get_swarms actually see.
    return pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "time": times,
            "latitude": [base_lat + i * spread for i in range(n)],
            "longitude": [-161.9 + i * spread for i in range(n)],
            "depth": [5.0] * n,
            "mag": [1.5] * n,
        }
    )


# ---------------------------------------------------------------------------
# build_download_url
# ---------------------------------------------------------------------------
def test_build_download_url_includes_time_window_and_depth(monkeypatch):
    """build_download_url composes an FDSN CSV query with start/end/maxdepth."""
    monkeypatch.setenv("FDSN_URL", "https://example/query?")
    url = build_download_url(T0, _swarm_config())
    assert url.startswith("https://example/query?")
    assert "starttime=2025-01-01T00:00:00" in url
    assert "endtime=2025-01-01T01:00:00" in url
    assert "maxdepth=50" in url
    assert url.endswith("format=csv")


# ---------------------------------------------------------------------------
# get_swarms
# ---------------------------------------------------------------------------
def test_get_swarms_clusters_adjacent_events_into_a_group():
    """get_swarms returns a cluster when enough close, recent events are present."""
    df = _events(5)
    swarms = get_swarms(df, T0, _swarm_config())
    assert len(swarms) == 1
    assert len(swarms[0]) == 5


def test_get_swarms_returns_no_group_below_min_num_evt():
    """get_swarms finds no cluster when fewer than min_num_evt events exist."""
    df = _events(2)  # below min_num_evt=3
    swarms = get_swarms(df, T0, _swarm_config())
    assert swarms == []


# ---------------------------------------------------------------------------
# compare_swarms
# ---------------------------------------------------------------------------
def test_compare_swarms_drops_duplicate_groups():
    """compare_swarms collapses two identical swarm groups down to one."""
    df = _events(4)
    swarms = compare_swarms([df.copy(), df.copy()])
    assert len(swarms) == 1


def test_compare_swarms_keeps_shorter_of_two_overlapping_groups():
    """compare_swarms merges on event_id and keeps the shorter-duration group.

    Two groups that share events (overlap) but are not identical: a short 4-event
    burst and a longer 6-event group that contains the same 4 plus 2 spread over
    more time. compare_swarms should drop the longer one and keep the short one.
    Guards the real column names (event_id/time) -- the merge previously keyed on
    a non-existent 'id' column and read a non-existent 'Time', so any run with 2+
    overlapping swarms raised.
    """
    short = _events(4, start="2025-01-01 00:50:00", step_s=60)        # 4 events, ~3 min
    long = _events(6, start="2025-01-01 00:30:00", step_s=300)        # 6 events, ~25 min
    # Make them overlap by sharing two event_ids.
    long.loc[0, "event_id"] = short.loc[0, "event_id"]
    long.loc[1, "event_id"] = short.loc[1, "event_id"]

    kept = compare_swarms([short.copy(), long.copy()])
    assert len(kept) == 1
    # The shorter-duration group (4 events) is the one kept.
    assert len(kept[0]) == 4


def test_compare_swarms_keeps_two_non_overlapping_groups():
    """compare_swarms leaves two disjoint swarms (no shared events) untouched.

    Exercises the 2-swarm path end to end (the merge that previously crashed) for
    genuinely simultaneous swarms at different locations -- both are kept.
    """
    a = _events(4, base_lat=55.40, start="2025-01-01 00:40:00")
    b = _events(4, base_lat=60.00, start="2025-01-01 00:40:00")
    b["event_id"] = [f"b{i}" for i in range(4)]  # disjoint ids
    kept = compare_swarms([a.copy(), b.copy()])
    assert len(kept) == 2


# ---------------------------------------------------------------------------
# check_swarm_continue
# ---------------------------------------------------------------------------
def test_check_swarm_continue_returns_only_new_events():
    """check_swarm_continue reports the new events that extend a prior swarm."""
    old = _events(4)
    # New batch: the same 4 plus one fresh event, all still clustered.
    new = _events(5)
    cont = check_swarm_continue(T0, _swarm_config(), old, new)
    # The continuation contains only the fifth (previously unseen) event id.
    assert len(cont) == 1
    assert set(cont[0]["event_id"]) == {"e4"}
