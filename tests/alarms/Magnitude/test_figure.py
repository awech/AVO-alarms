"""Smoke test for ``volc_alarms.alarms.Magnitude.figure.plot_event``.

``plot_event`` resolves the pick stations' coordinates (eq_picks_to_dataframe),
downloads a short waveform window for the nearest stations, removes their
instrument response, and draws a trace-mosaic + map figure for the event. This
drives that whole render for a real recorded M3.25 event near Denison
(2026-01-04) entirely offline, from committed fixtures:

  - magnitude_Denison_...quakeml  the per-event QuakeML (picks -> station list)
  - magnitude_Denison_...mseed    70 s waveforms for the nearest 10 BHZ channels
  - magnitude_Denison_..._inv.xml StationXML: coords for all 41 pick stations +
                                  full responses for the 10 recorded channels

The two network boundaries are faked: ``download_waveforms`` serves the recorded
MiniSEED, and ``Earthscope_client`` is a local-inventory shim serving station
coords + responses from the StationXML (so eq_picks_to_dataframe and
``st.remove_response`` run offline). ``save_file`` is mocked to a sentinel so no
jpg is written; matplotlib runs headless on Agg. Like the other figure tests
this is a *smoke* test: it asserts the render runs end to end and returns a path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from obspy import Stream, UTCDateTime, read, read_events, read_inventory

from volc_alarms.alarms.Magnitude import figure as mag_figure

pytestmark = pytest.mark.unit

DATA = "tests/fixtures/data"
STEM = f"{DATA}/magnitude_Denison_20260104T2016"
QUAKEML = f"{STEM}.quakeml"
MSEED = f"{STEM}.mseed"
INV = f"{STEM}_inv.xml"

SENTINEL_JPG = "/tmp/__sentinel_magnitude_figure__.jpg"


class _LocalInventoryClient:
    """Offline Earthscope-client stand-in backed by the fixture StationXML.

    Implements the surface plot_event exercises: ``get_stations`` (for
    eq_picks_to_dataframe's per-station coord lookups) and ``_attach_responses``
    (so ``st.remove_response`` in plot_station_traces works from the fixture
    responses). All served from the local inventory -- no network.
    """

    def __init__(self, inv_path):
        self._inv = read_inventory(str(inv_path))

    def get_stations(self, network=None, station=None, location=None,
                     channel=None, starttime=None, endtime=None, level=None, **_):
        sel = self._inv.select(
            network=network or "*", station=station or "*",
            location=location if location not in (None, "") else "*",
            channel=channel or "*",
        )
        if starttime is not None:
            sel = sel.select(time=starttime)
        if sel is None or len(sel) == 0:
            raise Exception(f"No stations for {network}.{station}.{location}.{channel}")
        return sel

    def _attach_responses(self, st):
        for tr in st:
            try:
                tr.stats.response = self._inv.get_response(tr.id, tr.stats.starttime)
            except Exception:
                pass


@pytest.fixture
def wired(monkeypatch):
    """Serve recorded waveforms + a local-inventory client; sentinel save_file."""
    recorded = read(MSEED)
    local_client = _LocalInventoryClient(INV)

    def _download(nslc_list, t1, t2):
        st = Stream()
        for nslc in nslc_list:
            sel = recorded.select(id=nslc)
            if sel:
                st += sel.copy().trim(t1, t2)
        return st

    # plot_event uses figure.downloading for both download_waveforms and (via
    # plot_station_traces) Earthscope_client; eq_picks_to_dataframe uses the
    # name-bound Earthscope_client in processing.
    monkeypatch.setattr(mag_figure.downloading, "download_waveforms", _download)
    monkeypatch.setattr(mag_figure.downloading, "Earthscope_client", lambda: local_client)
    monkeypatch.setattr(mag_figure.processing, "Earthscope_client", lambda: local_client)
    monkeypatch.setattr(mag_figure.plotting, "save_file", lambda *a, **k: SENTINEL_JPG)


def _config():
    return SimpleNamespace(alarm_name="Earthquake Magnitude")


def _event():
    return read_events(QUAKEML)[0]


def _volcs(eq):
    """volcano-distance table as process_event builds it, for the event origin."""
    from volc_alarms.utils import processing
    from volc_alarms.utils.setup_utils import load_volcano_list

    origin = eq.preferred_origin()
    return processing.volcano_distance(origin.longitude, origin.latitude, load_volcano_list())


def test_plot_event_runs_and_returns_path(wired):
    """plot_event renders the recorded Denison event end to end and returns a path."""
    eq = _event()
    result = mag_figure.plot_event(eq, _volcs(eq), _config(), test=False)
    assert result == SENTINEL_JPG


def test_plot_event_removes_response_from_recorded_traces(wired):
    """The response-removal path runs on the recorded traces (velocity units).

    Confirms the fixture StationXML responses attach + deconvolve without error;
    a nearby M3.25 yields mm/s-scale ground velocity, so the peak is well under
    1 m/s but non-zero.
    """
    from obspy import read as _read

    st = _read(MSEED)
    client = _LocalInventoryClient(INV)
    client._attach_responses(st)
    st.remove_response()
    peak = max(abs(tr.data).max() for tr in st)
    assert 0.0 < peak < 1.0
