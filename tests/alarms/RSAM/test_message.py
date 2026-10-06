"""Unit tests for ``volc_alarms.alarms.RSAM.message.create_message``.

These build the RSAM alert text from crafted station/level arrays. No network
or rendering is involved (``format_timestring`` reads only the TIMEZONE env var,
set to UTC by the top-level conftest).

Covered:
* create_message — subject line, per-station lines, exceedance markers, arrestor
* create_message — includes reduced-displacement (RD) values when provided
"""

from __future__ import annotations

import numpy as np
import pytest
from obspy import UTCDateTime

from volc_alarms.alarms.RSAM.message import create_message

pytestmark = pytest.mark.unit

T1 = UTCDateTime("2025-01-01T00:00:00")
T2 = UTCDateTime("2025-01-01T00:10:00")


def test_create_message_marks_exceeding_stations_and_lists_arrestor():
    """create_message stars stations above threshold and appends the arrestor line."""
    stations = ["CEAP", "CERA", "AMKA"]     # last entry is the arrestor
    rsam = np.array([300.0, 50.0, 20.0])
    levels = np.array([100.0, 100.0, 100.0])

    subject, message = create_message(T1, T2, stations, rsam, levels, DR=[], alarm_name="Cleveland RSAM")

    assert subject == "--- Cleveland RSAM ---"
    # CEAP exceeds its level -> starred; CERA does not.
    assert "CEAP*: 300/100" in message
    assert "CERA: 50/100" in message
    # Arrestor is reported on its own line.
    assert "Arrestor: AMKA 20/100" in message


def test_create_message_includes_reduced_displacement_when_present():
    """create_message adds the RD value per station when DR is non-empty."""
    stations = ["CEAP", "AMKA"]
    rsam = np.array([300.0, 20.0])
    levels = np.array([100.0, 100.0])
    DR = [4.2, 0.0]

    _, message = create_message(T1, T2, stations, rsam, levels, DR=DR, alarm_name="Cleveland RSAM")

    assert "CEAP*: 300/100 (RD = 4.2)" in message
