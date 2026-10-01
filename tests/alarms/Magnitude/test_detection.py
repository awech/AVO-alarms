"""Unit tests for ``volc_alarms.alarms.Magnitude.detection.process_event``.

``process_event`` downloads a hypocenter XML, finds nearby volcanoes, renders a
figure, and builds an alert message. Here the XML download and the figure
builder are locally mocked so the test runs offline and without matplotlib; the
volcano lookup uses the bundled test volcano list.

Covered:
* process_event — returns (subject, message, filename, eq, volcs) with the
  magnitude, coordinates, and nearest volcano reflected in the text
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from obspy import UTCDateTime
from obspy.core.event import (
    Catalog,
    Event,
    Magnitude,
    Origin,
    ResourceIdentifier,
)

from volc_alarms.alarms.Magnitude import detection as mag_detection

pytestmark = pytest.mark.unit


def _catalog_near_pavlof():
    origin = Origin(
        latitude=55.4173,
        longitude=-161.8937,
        depth=5000.0,
        time=UTCDateTime("2025-01-01T00:00:00"),
        evaluation_mode="manual",
    )
    mag = Magnitude(mag=3.2)
    event = Event(
        resource_id=ResourceIdentifier(id="smi:local/event/ak0258testevt"),
        origins=[origin],
        magnitudes=[mag],
    )
    event.preferred_origin_id = origin.resource_id
    event.preferred_magnitude_id = mag.resource_id
    return Catalog(events=[event])


def test_process_event_builds_message_with_magnitude_and_nearest_volcano(monkeypatch):
    """process_event returns a subject/message reflecting the event mag and nearest volcano."""
    # Mock the network XML fetch and the (matplotlib) figure builder.
    monkeypatch.setattr(
        mag_detection.downloading,
        "download_hypocenter_xml",
        lambda url: _catalog_near_pavlof(),
    )
    monkeypatch.setattr(
        mag_detection, "plot_event", lambda eq, volcs, config, test=False: Path("fig.jpg")
    )

    subject, message, filename, eq, volcs = mag_detection.process_event(
        "http://example/event", SimpleNamespace(), test=False
    )

    assert subject.startswith("M3.2 earthquake at ")
    assert "**Magnitude:** 3.2" in message
    assert "**Latitude:** 55.417" in message
    # The nearest volcano to (55.42, -161.89) is Pavlof.
    assert "Pavlof" in subject
    # The returned catalog event and volcano table are passed through.
    assert eq.preferred_magnitude().mag == 3.2
    assert "distance" in volcs.columns
