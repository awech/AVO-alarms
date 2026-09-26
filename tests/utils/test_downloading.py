"""Unit tests for ``volc_alarms.utils.downloading`` (offline paths only).

These cover the pure trace-QC helper and the HTTP retry wrappers with
``requests.get`` monkeypatched, so no real network I/O occurs. The waveform
fetchers (``download_waveforms``/FDSN/Winston) require a live data source and
are exercised via the integration harness instead.

Covered:
* _qc_sub_trace           — int32 cast + sampling-rate rounding
* download_hypocenters_csv — parses CSV body; None after repeated failures
* download_hypocenter_xml  — None on empty body; empty Catalog on bad payload

TODO: download_waveforms / Earthscope_client / download_station_xml need a live
or heavily-faked FDSN/Winston client; covered via integration, not here.
"""

from __future__ import annotations

import numpy as np
import pytest
from obspy import Catalog, Trace

from volc_alarms.utils import downloading

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _qc_sub_trace
# ---------------------------------------------------------------------------
def test_qc_sub_trace_casts_to_int32_and_rounds_sampling_rate():
    """_qc_sub_trace converts data to int32 and rounds a fractional sampling rate."""
    tr = Trace(data=np.array([1.0, 2.0, 3.0], dtype="float64"))
    tr.stats.sampling_rate = 99.7

    out = downloading._qc_sub_trace(tr)

    assert out.data.dtype.name == "int32"
    assert out.stats.sampling_rate == 100.0


# ---------------------------------------------------------------------------
# download_hypocenters_csv
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content


def test_download_hypocenters_csv_parses_response_body(monkeypatch):
    """download_hypocenters_csv parses the CSV body and renames id -> event_id."""
    csv = (
        "time,latitude,longitude,depth,mag,id\n"
        "2025-01-01T00:00:00,55.4,-161.9,5.0,3.2,ak0258\n"
    )
    monkeypatch.setattr(
        downloading.requests, "get", lambda *a, **k: _FakeResponse(csv.encode("utf-8"))
    )

    df = downloading.download_hypocenters_csv("http://example/query")

    assert list(df["event_id"]) == ["ak0258"]
    assert df.iloc[0]["mag"] == 3.2


def test_download_hypocenters_csv_returns_none_after_failures(monkeypatch):
    """download_hypocenters_csv returns None when every attempt raises."""
    def _boom(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(downloading.requests, "get", _boom)
    monkeypatch.setattr(downloading.time, "sleep", lambda s: None)  # no real waiting

    assert downloading.download_hypocenters_csv("http://example/query") is None


# ---------------------------------------------------------------------------
# download_hypocenter_xml
# ---------------------------------------------------------------------------
def test_download_hypocenter_xml_returns_none_on_empty_body(monkeypatch):
    """download_hypocenter_xml returns None when the response body is empty."""
    monkeypatch.setattr(
        downloading.requests, "get", lambda *a, **k: _FakeResponse(b"")
    )
    monkeypatch.setattr(downloading.time, "sleep", lambda s: None)

    assert downloading.download_hypocenter_xml("http://example/query") is None


def test_download_hypocenter_xml_returns_empty_catalog_on_bad_payload(monkeypatch):
    """download_hypocenter_xml returns an empty Catalog when the body can't be unpickled."""
    monkeypatch.setattr(
        downloading.requests, "get", lambda *a, **k: _FakeResponse(b"not-a-quakeml")
    )

    result = downloading.download_hypocenter_xml("http://example/query")

    assert isinstance(result, Catalog)
    assert len(result) == 0
