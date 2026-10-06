"""Unit tests for ``volc_alarms.alarms.SO2.detection``.

The SO2 detection module is almost entirely network/IO: ``download_SO2`` scrapes
a webpage and ``get_so2_images`` downloads + converts images. There is no pure
business logic to unit-test, so we only cover the offline failure path of the
scraper (retries then returns ``(None, None)``) with ``requests.get`` mocked.

Covered:
* download_SO2 — returns (None, None) after exhausting retries on a network error

TODO: get_so2_images and the successful scrape path require live HTML + PIL and
are exercised via the integration path.
"""

from __future__ import annotations

import pytest

from volc_alarms.alarms.SO2 import detection as so2_detection

pytestmark = pytest.mark.unit


def test_download_so2_returns_none_pair_after_failed_requests(monkeypatch):
    """download_SO2 returns (None, None) when every scrape attempt raises."""
    def _boom(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(so2_detection.requests, "get", _boom)
    monkeypatch.setattr(so2_detection.time, "sleep", lambda s: None)  # no real waiting
    monkeypatch.setenv("SACS_URL", "https://example/sacs")

    table, soup = so2_detection.download_SO2()

    assert table is None
    assert soup is None
