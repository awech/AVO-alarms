"""Unit tests for ``volc_alarms.alarms.VAA.message.create_message``.

These build crafted ``vaa`` dicts (a plain dict is enough: create_message reads
VOLCANO/time and iterates keys) and assert the advisory message carries the
distinct OBS flight levels on its ``VAA `` line. No network or rendering.

Covered:
* create_message — multi-ring OBS field lists both distinct levels
* create_message — single-ring OBS field lists its single level
* create_message — no unpack error is logged for the multi-ring list contract
"""

from __future__ import annotations

import logging

import pytest

from volc_alarms.alarms.VAA.message import create_message

pytestmark = pytest.mark.unit

OBS = "OBS VA CLD"

TWO_RING_OBS_CLD = (
    "FL100/FL340 N4941 W16417 - N4750 W16033 - N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 N5723 E17430 - N5448 W17024 - N5723 E17430 MOV SE 50KT"
)
SINGLE_RING_OBS_CLD = "SFC/060 N5817 W15498 - N5730 W15400 - N5817 W15498"


def _vaa(cloud_field):
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "time": "2025-01-01T00:00:00",
        OBS: cloud_field,
    }


def test_create_message_lists_distinct_levels_for_multi_ring_field():
    """create_message puts both distinct OBS levels on the VAA line for a two-ring field."""
    subject, message = create_message(_vaa(TWO_RING_OBS_CLD))
    # VOLCANO tokens minus the trailing id are joined and title-cased.
    assert subject == "Mtkatmai Volcanic Ash Advisory"
    assert "VAA 10,000 - 34,000 ft, 10,000 - 28,000 ft" in message
    # The VAA line carries the levels rather than falling into the generic
    # "Volcanic Ash Advisory" except branch (which omits the level line).
    assert message.startswith("VAA 10,000 - 34,000 ft, 10,000 - 28,000 ft")


def test_create_message_lists_single_level_for_single_ring_field():
    """create_message puts the single OBS level on the VAA line for a one-ring field."""
    _, message = create_message(_vaa(SINGLE_RING_OBS_CLD))
    assert "VAA 0 - 6,000 ft" in message


def test_create_message_does_not_log_generation_error(caplog):
    """create_message consumes the ring list without logging a message-generation error."""
    with caplog.at_level(logging.WARNING):
        create_message(_vaa(TWO_RING_OBS_CLD))
    assert "Error generating message contents" not in caplog.text
