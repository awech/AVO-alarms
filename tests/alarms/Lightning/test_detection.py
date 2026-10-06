"""Unit tests for ``volc_alarms.alarms.Lightning.detection``.

These call the Lightning detection helpers directly with crafted DataFrames and
a minimal config. No network is used (``download_lightning`` shells out to curl
and is covered via the integration path).

Covered:
* inner_outer       — split stroke counts by the inner-ring distance threshold
* get_direction     — azimuth -> 16-point compass label (incl. wraparound)
* get_state_message — WARNING/CRITICAL state text with ring counts + window
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from volc_alarms.alarms.Lightning.detection import (
    get_direction,
    get_state_message,
    inner_outer,
)

pytestmark = pytest.mark.unit


def _config():
    return SimpleNamespace(dist1=20.0, dist2=100.0, duration=3600)


# ---------------------------------------------------------------------------
# inner_outer
# ---------------------------------------------------------------------------
def test_inner_outer_splits_counts_at_inner_ring_distance():
    """inner_outer counts strokes inside dist1 vs the remainder."""
    df = pd.DataFrame({"v_distance": [5.0, 10.0, 25.0, 80.0]})
    n_ring1, n_ring2 = inner_outer(df, _config())
    assert n_ring1 == 2   # 5, 10 km are within 20 km
    assert n_ring2 == 2   # 25, 80 km are outside


# ---------------------------------------------------------------------------
# get_direction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "azimuth, expected",
    [
        (0, "N"),
        (90, "E"),
        (180, "S"),
        (270, "W"),
        (45, "NE"),
        (359, "N"),   # wraps back to N
    ],
)
def test_get_direction_maps_azimuth_to_compass_point(azimuth, expected):
    """get_direction converts an azimuth in degrees to a 16-point compass label."""
    assert get_direction(azimuth) == expected


# ---------------------------------------------------------------------------
# get_state_message
# ---------------------------------------------------------------------------
def test_get_state_message_critical_includes_stroke_total():
    """get_state_message CRITICAL text reports the total new strokes and ring split."""
    msg = get_state_message("CRITICAL", "2025-01-01 00:00", "Pavlof", 3, 2, _config())
    assert "Pavlof Lightning Detection!" in msg
    assert "5 new strokes!" in msg
    assert "3 strokes < 20 km" in msg
    assert "past 60 minutes" in msg


def test_get_state_message_warning_uses_distal_wording_when_strokes_present():
    """get_state_message WARNING says 'Distal' when any strokes are counted."""
    msg = get_state_message("WARNING", "2025-01-01 00:00", "Pavlof", 0, 2, _config())
    assert "Distal Lightning Detection!" in msg
