"""Unit tests for ``volc_alarms.utils.downloading`` (offline paths only).

No real network I/O occurs: ``requests.get``, the obspy FDSN/Winston/Earthscope
clients, the ``Inventory`` writer, and the QuakeML ``Unpickler`` are all
monkeypatched with local fakes. The integration harness still drives the same
fetchers end to end against frozen baselines.

Covered:
* _qc_sub_trace            — int32 cast + sampling-rate rounding
* download_hypocenters_csv — CSV parse, time normalization, None after failures
* download_hypocenter_xml  — None on empty body, empty/real Catalog on payload
* Earthscope_client        — first-success return, None after three failures
* download_waveforms       — Winston vs FDSN client, zero-fill on no-data/error
* download_vaa_from_nws_api — @graph on success, None after failures
* _extract_nslc_from_config — RSAM (stations/infrasound/arrestor) + Tremor shapes
* _collect_station_nslc    — glob + sorted unique union across seismic configs
* download_station_xml     — atomic write, FDSNNoData all-epochs fallback
"""

from __future__ import annotations

from pathlib import Path

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


# ---------------------------------------------------------------------------
# download_hypocenters_csv — success path with populated time column
# ---------------------------------------------------------------------------
def test_download_hypocenters_csv_normalizes_time_column(monkeypatch):
    """download_hypocenters_csv coerces the time column to datetime for non-empty data."""
    import pandas as pd

    csv = (
        "time,latitude,longitude,depth,mag,id\n"
        "2025-01-01T00:00:00,55.4,-161.9,5.0,3.2,ak0258\n"
        "2025-01-02T12:30:45,55.5,-162.0,7.0,2.9,ak0259\n"
    )
    monkeypatch.setattr(
        downloading.requests, "get", lambda *a, **k: _FakeResponse(csv.encode("utf-8"))
    )

    df = downloading.download_hypocenters_csv("http://example/query")

    assert len(df) == 2
    assert pd.api.types.is_datetime64_any_dtype(df["time"])
    assert list(df["event_id"]) == ["ak0258", "ak0259"]


# ---------------------------------------------------------------------------
# download_hypocenter_xml — success path (real QuakeML unpickled)
# ---------------------------------------------------------------------------
def test_download_hypocenter_xml_unpickles_catalog(monkeypatch):
    """download_hypocenter_xml returns the Catalog produced by the Unpickler."""
    sentinel = Catalog()

    class _FakeUnpickler:
        def loads(self, body):
            return sentinel

    monkeypatch.setattr(
        downloading.requests, "get", lambda *a, **k: _FakeResponse(b"<quakeml/>")
    )
    monkeypatch.setattr(downloading, "Unpickler", _FakeUnpickler)

    result = downloading.download_hypocenter_xml("http://example/query")

    assert result is sentinel


# ---------------------------------------------------------------------------
# Earthscope_client
# ---------------------------------------------------------------------------
def test_earthscope_client_returns_client_on_first_success(monkeypatch):
    """Earthscope_client returns the FDSN client when construction succeeds."""
    sentinel = object()
    monkeypatch.setattr(
        downloading, "FDSN_Client", lambda *a, **k: sentinel
    )
    assert downloading.Earthscope_client() is sentinel


def test_earthscope_client_returns_none_after_three_failures(monkeypatch):
    """Earthscope_client gives up and returns None after three failed attempts."""
    attempts = {"n": 0}

    def _boom(*a, **k):
        attempts["n"] += 1
        raise ConnectionError("no route")

    monkeypatch.setattr(downloading, "FDSN_Client", _boom)
    monkeypatch.setattr(downloading.time, "sleep", lambda s: None)

    assert downloading.Earthscope_client() is None
    assert attempts["n"] == 3


# ---------------------------------------------------------------------------
# download_waveforms
# ---------------------------------------------------------------------------
class _FakeClient:
    """Stand-in waveform client returning canned traces per NSLC."""

    def __init__(self, returns):
        # returns: dict nslc -> Stream/Trace, or an Exception to raise
        self._returns = returns
        self.requested = []

    def get_waveforms(self, net, sta, loc, chan, T1, T2):
        nslc = f"{net}.{sta}.{loc}.{chan}"
        self.requested.append(nslc)
        value = self._returns.get(nslc)
        if isinstance(value, Exception):
            raise value
        return value


def test_download_waveforms_uses_winston_by_default(monkeypatch):
    """download_waveforms builds an earthworm (Winston) client when USE_EARTHSCOPE is unset."""
    from obspy import Stream, UTCDateTime

    monkeypatch.delenv("USE_EARTHSCOPE", raising=False)
    monkeypatch.setenv("WINSTON_HOST", "127.0.0.1")
    monkeypatch.setenv("WINSTON_PORT", "16022")
    monkeypatch.setenv("TIMEOUT", "20")

    T1 = UTCDateTime("2025-01-01T00:00:00")
    T2 = UTCDateTime("2025-01-01T00:01:00")
    good = Stream([Trace(data=np.ones(6000, dtype="int32"))])
    good[0].stats.sampling_rate = 100
    good[0].stats.starttime = T1

    created = {}

    def _ew_client(host, port, timeout=None):
        created["host"] = host
        created["port"] = port
        return _FakeClient({"AV.PS4A..BHZ": good})

    monkeypatch.setattr(downloading, "EW_Client", _ew_client)

    st = downloading.download_waveforms(["AV.PS4A..BHZ"], T1, T2)

    assert created["host"] == "127.0.0.1"
    assert created["port"] == 16022
    assert len(st) == 1


def test_download_waveforms_uses_fdsn_when_earthscope_set(monkeypatch):
    """download_waveforms builds an FDSN client when USE_EARTHSCOPE is set."""
    from obspy import Stream, UTCDateTime

    monkeypatch.setenv("USE_EARTHSCOPE", "1")

    T1 = UTCDateTime("2025-01-01T00:00:00")
    T2 = UTCDateTime("2025-01-01T00:01:00")
    tr = Trace(data=np.ones(6000, dtype="int32"))
    tr.stats.sampling_rate = 100
    tr.stats.starttime = T1

    def _fdsn(*a, **k):
        return _FakeClient({"AV.PS4A..BHZ": Stream([tr])})

    monkeypatch.setattr(downloading, "FDSN_Client", _fdsn)

    st = downloading.download_waveforms(["AV.PS4A..BHZ"], T1, T2)
    assert len(st) == 1


def test_download_waveforms_fills_zeros_on_missing_data(monkeypatch):
    """download_waveforms substitutes a zero-filled trace when a channel returns nothing."""
    from obspy import Stream, UTCDateTime

    monkeypatch.delenv("USE_EARTHSCOPE", raising=False)
    monkeypatch.setenv("WINSTON_HOST", "127.0.0.1")
    monkeypatch.setenv("WINSTON_PORT", "16022")
    monkeypatch.setenv("TIMEOUT", "20")

    T1 = UTCDateTime("2025-01-01T00:00:00")
    T2 = UTCDateTime("2025-01-01T00:01:00")  # 60 s -> 6000 samples at 100 Hz

    # Empty stream for the channel -> triggers the zero-fill branch.
    monkeypatch.setattr(
        downloading, "EW_Client",
        lambda *a, **k: _FakeClient({"AV.PS4A..BHZ": Stream()}),
    )

    st = downloading.download_waveforms(["AV.PS4A..BHZ"], T1, T2)

    assert len(st) == 1
    assert st[0].id == "AV.PS4A..BHZ"
    assert np.all(st[0].data == 0)
    assert st[0].stats.npts == 6000


def test_download_waveforms_fills_zeros_on_client_exception(monkeypatch):
    """download_waveforms recovers from a client error by zero-filling the channel."""
    from obspy import UTCDateTime

    monkeypatch.delenv("USE_EARTHSCOPE", raising=False)
    monkeypatch.setenv("WINSTON_HOST", "127.0.0.1")
    monkeypatch.setenv("WINSTON_PORT", "16022")
    monkeypatch.setenv("TIMEOUT", "20")

    T1 = UTCDateTime("2025-01-01T00:00:00")
    T2 = UTCDateTime("2025-01-01T00:01:00")

    monkeypatch.setattr(
        downloading, "EW_Client",
        lambda *a, **k: _FakeClient({"AV.PS4A..BHZ": RuntimeError("timeout")}),
    )

    st = downloading.download_waveforms(["AV.PS4A..BHZ"], T1, T2)

    assert len(st) == 1
    assert np.all(st[0].data == 0)


# ---------------------------------------------------------------------------
# download_vaa_from_nws_api
# ---------------------------------------------------------------------------
class _FakeJsonResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_download_vaa_from_nws_api_returns_graph(monkeypatch):
    """download_vaa_from_nws_api returns the @graph list on a successful response."""
    monkeypatch.setenv("VAA_URL", "https://example/vaa")
    graph = [{"id": "1"}, {"id": "2"}]
    monkeypatch.setattr(
        downloading.requests, "get",
        lambda *a, **k: _FakeJsonResponse({"@graph": graph}),
    )

    assert downloading.download_vaa_from_nws_api() == graph


def test_download_vaa_from_nws_api_returns_none_after_failures(monkeypatch):
    """download_vaa_from_nws_api returns None when all attempts fail."""
    monkeypatch.setenv("VAA_URL", "https://example/vaa")

    def _boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(downloading.requests, "get", _boom)

    assert downloading.download_vaa_from_nws_api() is None


# ---------------------------------------------------------------------------
# _extract_nslc_from_config
# ---------------------------------------------------------------------------
def test_extract_nslc_from_rsam_config():
    """_extract_nslc_from_config pulls stations, infrasound, and arrestor NSLC for RSAM."""
    config = {
        "alarm_type": "RSAM",
        "rsam_stations": [
            {"nslc": "AV.SSLW..BHZ", "value": 300},
            {"nslc": "AV.SSLS..BHZ", "value": 300},
        ],
        "infrasound": ["AV.SSLW..BDF"],
        "arrestor": {"nslc": "AV.SPCP..BHZ", "value": 100},
    }
    nslc = downloading._extract_nslc_from_config(config)
    assert nslc == ["AV.SSLW..BHZ", "AV.SSLS..BHZ", "AV.SSLW..BDF", "AV.SPCP..BHZ"]


def test_extract_nslc_from_infrasound_config():
    """_extract_nslc_from_config returns the top-level nslc list for Infrasound."""
    config = {"alarm_type": "Infrasound", "nslc": ["AV.SDPI.01.HDF", "AV.SDPI.02.HDF"]}
    nslc = downloading._extract_nslc_from_config(config)
    assert nslc == ["AV.SDPI.01.HDF", "AV.SDPI.02.HDF"]


def test_extract_nslc_from_tremor_config():
    """_extract_nslc_from_config returns the top-level nslc list for Tremor."""
    config = {"alarm_type": "Tremor", "nslc": ["AV.PVV..BHZ", "AV.PS4A..BHZ"]}
    nslc = downloading._extract_nslc_from_config(config)
    assert nslc == ["AV.PVV..BHZ", "AV.PS4A..BHZ"]


def test_extract_nslc_from_rsam_config_without_arrestor():
    """_extract_nslc_from_config tolerates a missing arrestor key."""
    config = {"alarm_type": "RSAM", "rsam_stations": [{"nslc": "AV.SSLW..BHZ", "value": 300}]}
    assert downloading._extract_nslc_from_config(config) == ["AV.SSLW..BHZ"]


def test_extract_nslc_from_non_seismic_config_returns_empty():
    """_extract_nslc_from_config returns [] for a non-seismic alarm type."""
    assert downloading._extract_nslc_from_config({"alarm_type": "Lightning"}) == []


def test_extract_nslc_from_config_missing_alarm_type_returns_empty():
    """_extract_nslc_from_config returns [] (no KeyError) when alarm_type is absent."""
    assert downloading._extract_nslc_from_config({"some": "mapping"}) == []


# ---------------------------------------------------------------------------
# _collect_station_nslc
# ---------------------------------------------------------------------------
def test_collect_station_nslc_unions_and_dedupes(tmp_path):
    """_collect_station_nslc globs seismic configs and returns a sorted unique union."""
    (tmp_path / "Semisopochnoi_RSAM.yml").write_text(
        "alarm_type: RSAM\n"
        "rsam_stations:\n"
        "  - nslc: AV.CERB..BHZ\n"
        "    value: 300\n"
        "arrestor:\n"
        "   nslc: AV.CESW..BHZ\n"
        "   value: 100\n"
    )
    (tmp_path / "Cleveland_Tremor.yml").write_text(
        "alarm_type: Tremor\n"
        "nslc:\n"
        "   - AV.CLCO..BHZ\n"
        "   - AV.CERB..BHZ\n"  # CERB duplicates RSAM
    )

    nslc = downloading._collect_station_nslc(tmp_path)

    assert list(nslc) == ["AV.CERB..BHZ", "AV.CESW..BHZ", "AV.CLCO..BHZ"]


def test_collect_station_nslc_skips_non_alarm_and_empty_yml(tmp_path):
    """_collect_station_nslc ignores *.yml files that are not alarm configs.

    The config dir also holds distribution.yml / phonebook.yml (no alarm_type)
    and may hold empty docs; these must be skipped, not raise.
    """
    (tmp_path / "RSAM.yml").write_text(
        "alarm_type: RSAM\n"
        "rsam_stations:\n"
        "  - nslc: AV.CERB..BHZ\n"
        "    value: 300\n"
    )
    # No alarm_type -> skipped (previously raised KeyError).
    (tmp_path / "distribution.yml").write_text("All Alarms:\n  - alice\n")
    (tmp_path / "phonebook.yml").write_text("alice: alice@example.com\n")
    # Empty doc -> yaml.safe_load returns None -> skipped (not a TypeError).
    (tmp_path / "empty.yml").write_text("")
    # A non-seismic alarm config -> recognized as a config but yields no NSLC.
    (tmp_path / "Lightning.yml").write_text("alarm_type: Lightning\n")

    nslc = downloading._collect_station_nslc(tmp_path)

    assert list(nslc) == ["AV.CERB..BHZ"]


# ---------------------------------------------------------------------------
# download_station_xml
# ---------------------------------------------------------------------------
def test_download_station_xml_writes_atomically(monkeypatch, tmp_path):
    """download_station_xml fetches stations, writes a temp file, then atomically replaces."""
    from obspy import UTCDateTime
    from obspy.core.inventory.inventory import Inventory

    # One seismic config so _collect_station_nslc yields a single channel.
    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    out_file = tmp_path / "stations.xml"
    monkeypatch.setenv("STATION_XML", str(out_file))
    (tmp_path / "X_RSAM.yml").write_text(
        "alarm_type: RSAM\n"
        "rsam_stations:\n"
        "  - nslc: AV.SSLW..BHZ\n"
        "    value: 300\n"
    )

    class _FakeInv:
        def __init__(self):
            self.written = None

        def __iadd__(self, other):
            return self

        def write(self, path, format=None):
            self.written = str(path)
            Path(path).write_text("<inv/>")

    fake_inv = _FakeInv()
    monkeypatch.setattr(downloading, "Inventory", lambda: fake_inv)

    class _FakeStationClient:
        def get_stations(self, **kwargs):
            return object()

    monkeypatch.setattr(downloading, "Earthscope_client", lambda: _FakeStationClient())
    monkeypatch.setattr(downloading.time, "sleep", lambda s: None)

    downloading.download_station_xml()

    # The temp file was renamed onto the final path.
    assert out_file.exists()
    assert fake_inv.written.endswith(".tmp")


def test_download_station_xml_falls_back_to_all_epochs(monkeypatch, tmp_path):
    """download_station_xml retries without starttime when no current epoch exists."""
    from obspy.clients.fdsn.header import FDSNNoDataException
    from obspy.core.inventory.inventory import Inventory

    monkeypatch.setenv("CONFIGS_DIR", str(tmp_path))
    out_file = tmp_path / "stations.xml"
    monkeypatch.setenv("STATION_XML", str(out_file))
    (tmp_path / "X_RSAM.yml").write_text(
        "alarm_type: RSAM\n"
        "rsam_stations:\n"
        "  - nslc: AV.SSLW..BHZ\n"
        "    value: 300\n"
    )

    class _FakeInv:
        def __iadd__(self, other):
            return self

        def write(self, path, format=None):
            Path(path).write_text("<inv/>")

    monkeypatch.setattr(downloading, "Inventory", lambda: _FakeInv())

    calls = {"n": 0}

    class _FakeStationClient:
        def get_stations(self, **kwargs):
            calls["n"] += 1
            # First call (with starttime) raises -> triggers the all-epochs retry.
            if "starttime" in kwargs:
                raise FDSNNoDataException("no epoch")
            return object()

    monkeypatch.setattr(downloading, "Earthscope_client", lambda: _FakeStationClient())
    monkeypatch.setattr(downloading.time, "sleep", lambda s: None)

    downloading.download_station_xml()

    assert calls["n"] == 2  # starttime attempt + all-epochs retry
    assert out_file.exists()
