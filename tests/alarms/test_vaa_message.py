"""Focused tests for VAA ``create_message()`` under the multi-ring list contract.

Follow-up to the ``vaa-resuspended-ash-polygon-parsing`` bugfix: a production
caller was missed when ``process_polygons()`` changed to return a LIST of
``(lons, lats, level_txt)`` groups. ``create_message()`` in
``src/volc_alarms/alarms/VAA/message.py`` still unpacked the OLD 3-tuple
(``lons_0, lats_0, level_0 = process_polygons(...)``), which raises
``not enough values to unpack (expected 3, got 1)`` on every VAA (swallowed by
the surrounding try/except, silently losing the level line).

The fix consumes the list and builds the OBS level string from the DISTINCT
non-empty ring levels, preserving insertion order (the same logic ``make_map``
uses for its title). These tests build crafted ``vaa`` dicts (a plain dict is
enough: ``create_message`` uses ``vaa["VOLCANO"]``, ``vaa["time"]`` and iterates
``vaa.keys()``) with real multi-ring and single-ring OBS fields, and assert the
``VAA `` line carries the distinct levels rather than falling into the generic
except branch.

**Validates: Requirements 2.4, 2.6, 2.11**
"""

from __future__ import annotations

import logging

from volc_alarms.alarms.VAA.message import create_message

OBS_FIELD = "OBS VA CLD"

# Real production TWO-RING OBS VA CLD field: two sub-polygons, each with its own
# FL bounds and coordinate ring, plus a trailing MOV <DIR> <N>KT motion token.
TWO_RING_OBS_CLD = (
    "FL100/FL340 N4941 W16417 - N4750 W16033 - N4941 W16417 MOV ESE 70KT\n"
    "FL100/FL280 N5723 E17430 - N5448 W17024 - N5723 E17430 MOV SE 50KT"
)

# Single-ring OBS field with an SFC lower bound and a bare-number upper bound.
SINGLE_RING_OBS_CLD = (
    "SFC/060 N5817 W15498 - N5730 W15400 - N5817 W15498"
)

MULTI_RING_LEVELS = "10,000 - 34,000 ft, 10,000 - 28,000 ft"
SINGLE_RING_LEVEL = "0 - 6,000 ft"


def _multi_ring_vaa():
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: TWO_RING_OBS_CLD,
    }


def _single_ring_vaa():
    return {
        "VOLCANO": "MT KATMAI 1102-06",
        "time": "2025-01-01T00:00:00",
        OBS_FIELD: SINGLE_RING_OBS_CLD,
    }


def test_multi_ring_message_lists_distinct_obs_levels():
    """Req 2.6 / 2.11 - a two-ring OBS field yields both distinct levels on the VAA line.

    create_message must not raise, must return a (subject, message) tuple, and
    the message's ``VAA `` line must carry the distinct OBS levels string.
    """
    vaa = _multi_ring_vaa()

    result = create_message(vaa)

    assert isinstance(result, tuple)
    assert len(result) == 2
    subject, message = result
    assert isinstance(subject, str)
    assert isinstance(message, str)

    # The message carries the distinct OBS levels on the VAA line, and did NOT
    # fall into the generic "Volcanic Ash Advisory" except branch.
    assert f"VAA {MULTI_RING_LEVELS}" in message
    assert "Volcanic Ash Advisory" not in message


def test_single_ring_message_lists_level():
    """Req 2.4 - a single-ring SFC/060 OBS field yields ``VAA 0 - 6,000 ft``."""
    vaa = _single_ring_vaa()

    subject, message = create_message(vaa)

    assert f"VAA {SINGLE_RING_LEVEL}" in message
    assert "Volcanic Ash Advisory" not in message


def test_multi_ring_message_does_not_log_generation_error(caplog):
    """The unpack error is gone: no WARNING about failed message generation."""
    vaa = _multi_ring_vaa()

    with caplog.at_level(logging.WARNING):
        create_message(vaa)

    assert "Error generating message contents" not in caplog.text
