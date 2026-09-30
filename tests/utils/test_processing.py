"""Unit tests for ``volc_alarms.utils.processing``.

These exercise the geodesy, volcano-lookup, and waveform-preprocessing helpers
with crafted DataFrames / obspy Streams. The only external file touched is the
in-repo test station XML (via ``add_metadata`` / ``remove_gain``); no network is
used.

Covered:
* volcano_distance    — distance column + ascending sort + filter_col opt-in
* find_nearest_volcano — nearest name/distance per input row (volc_df injected)
* preprocess_stream   — merge/trim to a gap-free window of the requested length
* add_metadata        — attaches coordinates + inventory from the station XML
* remove_gain         — divides out instrument sensitivity using that inventory
* addPhaseHint        — copies arrival phase onto the matching pick
* Dr_to_RSAM          — reduced-displacement -> per-station RSAM levels, with the
                        FDSN client served from the in-repo test station XML

TODO: eq_picks_to_dataframe also calls a live FDSN client for station responses;
it is exercised indirectly by the Magnitude figure test and is a candidate for a
mocked-client unit test in a later pass.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace, UTCDateTime, read_inventory

from volc_alarms.utils import processing

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _volc_df():
    """A tiny volcano table with a per-alarm opt-in column."""
    return pd.DataFrame(
        {
            "Name": ["Pavlof", "Shishaldin", "Cleveland"],
            "Latitude": [55.417, 54.756, 52.825],
            "Longitude": [-161.894, -163.970, -169.945],
            "PIREP": ["Y", "N", "Y"],
        }
    )


def _trace(nslc, t0, npts=6000, sr=100.0, value=1.0):
    net, sta, loc, chan = nslc.split(".")
    tr = Trace(data=np.full(npts, value, dtype="float64"))
    tr.stats.network = net
    tr.stats.station = sta
    tr.stats.location = loc
    tr.stats.channel = chan
    tr.stats.sampling_rate = sr
    tr.stats.starttime = t0
    return tr


class _Cfg:
    """Minimal preprocess config (taper + bandpass corners)."""
    taper = 5.0
    f1 = 1.0
    f2 = 10.0


# ---------------------------------------------------------------------------
# volcano_distance
# ---------------------------------------------------------------------------
def test_volcano_distance_adds_sorted_distance_column():
    """volcano_distance appends a km distance column sorted ascending."""
    volcs = _volc_df()
    # A point essentially on top of Pavlof.
    out = processing.volcano_distance(-161.894, 55.417, volcs)

    assert "distance" in out.columns
    # Sorted ascending, nearest first.
    assert list(out["distance"]) == sorted(out["distance"])
    assert out.iloc[0]["Name"] == "Pavlof"
    assert out.iloc[0]["distance"] < 1.0  # ~0 km from itself


def test_volcano_distance_filter_col_drops_opted_out_rows():
    """volcano_distance with filter_col drops rows whose column value is 'N'."""
    volcs = _volc_df()
    out = processing.volcano_distance(-161.894, 55.417, volcs, filter_col="PIREP")
    # Shishaldin is 'N' and must be excluded.
    assert "Shishaldin" not in list(out["Name"])
    assert set(out["Name"]) == {"Pavlof", "Cleveland"}


# ---------------------------------------------------------------------------
# find_nearest_volcano
# ---------------------------------------------------------------------------
def test_find_nearest_volcano_labels_each_row_with_nearest():
    """find_nearest_volcano adds v_name/v_distance for the closest volcano per row."""
    df = pd.DataFrame(
        {
            "longitude": [-161.894, -169.945],
            "latitude": [55.417, 52.825],
        }
    )
    out = processing.find_nearest_volcano(df, volc_df=_volc_df())

    assert list(out["v_name"]) == ["Pavlof", "Cleveland"]
    assert (out["v_distance"] < 1.0).all()  # each point sits on its volcano


# ---------------------------------------------------------------------------
# preprocess_stream
# ---------------------------------------------------------------------------
def test_preprocess_stream_trims_to_requested_window_gap_free():
    """preprocess_stream returns a merged, gap-free stream trimmed to [t1, t2]."""
    t0 = UTCDateTime("2025-01-01T00:00:00")
    st = Stream([_trace("AV.PS4A..BHZ", t0, npts=9000)])  # 90 s at 100 Hz
    t1 = t0 + 10
    t2 = t0 + 70

    out = processing.preprocess_stream(st, t1, t2, _Cfg())

    assert len(out) == 1
    tr = out[0]
    assert tr.stats.starttime == t1
    # 60-second window at 100 Hz -> 6000 samples (+1 endpoint sample).
    assert tr.stats.npts == pytest.approx(6001, abs=1)
    assert not out.get_gaps()


# ---------------------------------------------------------------------------
# add_metadata + remove_gain (use the in-repo test station XML)
# ---------------------------------------------------------------------------
def test_add_metadata_attaches_coordinates_and_inventory():
    """add_metadata attaches station coordinates and an inventory to each trace."""
    t0 = UTCDateTime("2025-01-01T00:00:00")
    st = Stream([_trace("AV.PS4A..BHZ", t0, npts=1000)])

    out = processing.add_metadata(st)

    tr = out[0]
    assert "coordinates" in tr.stats
    assert "latitude" in tr.stats.coordinates
    assert "longitude" in tr.stats.coordinates
    assert tr.stats.inventory is not None


def test_remove_gain_divides_out_instrument_sensitivity():
    """remove_gain scales trace data by the inventory sensitivity from add_metadata."""
    t0 = UTCDateTime("2025-01-01T00:00:00")
    st = Stream([_trace("AV.PS4A..BHZ", t0, npts=1000, value=1000.0)])
    processing.add_metadata(st)

    before_peak = float(np.max(np.abs(st[0].data)))
    out = processing.remove_gain(st)
    after_peak = float(np.max(np.abs(out[0].data)))

    # Sensitivity is a large counts/(m/s) value, so amplitudes shrink markedly.
    assert after_peak < before_peak


# ---------------------------------------------------------------------------
# addPhaseHint
# ---------------------------------------------------------------------------
def test_add_phase_hint_copies_arrival_phase_onto_matching_pick():
    """addPhaseHint stamps each pick's phase_hint from its matching arrival."""
    from obspy.core.event import (
        Arrival,
        Catalog,
        Event,
        Origin,
        Pick,
        ResourceIdentifier,
    )

    pick_id = ResourceIdentifier(id="smi:local/pick/1")
    pick = Pick(resource_id=pick_id, time=UTCDateTime("2025-01-01T00:00:05"))
    arrival = Arrival(pick_id=pick_id, phase="P")
    origin = Origin(
        time=UTCDateTime("2025-01-01T00:00:00"),
        latitude=55.4,
        longitude=-161.9,
        arrivals=[arrival],
    )
    event = Event(origins=[origin], picks=[pick])
    event.preferred_origin_id = origin.resource_id

    out = processing.addPhaseHint(Catalog(events=[event]))

    assert out[0].picks[0].phase_hint == "P"


# ---------------------------------------------------------------------------
# Dr_to_RSAM (FDSN client served from the test station XML)
# ---------------------------------------------------------------------------
class _LocalInventoryClient:
    """Offline FDSN-client stand-in: get_stations served from a StationXML."""

    def __init__(self, inv):
        self._inv = inv

    def get_stations(self, network=None, station=None, location=None,
                     channel=None, starttime=None, endtime=None, level=None, **_):
        return self._inv.select(
            network=network, station=station,
            location=location if location not in (None, "") else "*",
            channel=channel,
        )


@pytest.fixture
def local_fdsn_client(monkeypatch):
    """Point Dr_to_RSAM's FDSN_Client at the in-repo test station XML (no network)."""
    inv = read_inventory(os.environ["STATION_XML"])
    monkeypatch.setattr(processing, "FDSN_Client", lambda *a, **k: _LocalInventoryClient(inv))
    return inv


def _pavlof_rsam_config():
    """Minimal Pavlof RSAM config: the stations present in the test station XML."""
    return SimpleNamespace(
        volcano_name="Pavlof",
        rsam_stations=[
            {"nslc": "AV.PS4A..BHZ", "value": 400},
            {"nslc": "AV.PVV..BHZ", "value": 400},
            {"nslc": "AV.PN7A..BHZ", "value": 450},
        ],
        arrestor={"nslc": "AV.BLDW..BHZ", "value": 200},
    )


def test_dr_to_rsam_returns_per_station_levels(local_fdsn_client):
    """Dr_to_RSAM returns a level per station with real distances + computed RSAM."""
    config = _pavlof_rsam_config()
    table = processing.Dr_to_RSAM(100, config=config)

    # One row per source station + the arrestor.
    assert list(table["Station"]) == [
        "AV.PS4A..BHZ", "AV.PVV..BHZ", "AV.PN7A..BHZ", "AV.BLDW..BHZ"
    ]
    assert (table["Volcano"] == "Pavlof").all()
    assert (table["DR Level"] == 100).all()
    # All computed levels are positive and finite.
    assert (table["RSAM Level"] > 0).all()
    # The arrestor (BLDW, ~62 km) is much farther than the near-summit stations.
    dist = dict(zip(table["Station"], table["Distance (km)"]))
    assert dist["AV.PN7A..BHZ"] < dist["AV.BLDW..BHZ"]


def test_dr_to_rsam_level_decreases_with_distance(local_fdsn_client):
    """For a fixed DR, the modeled RSAM level is higher at closer stations."""
    config = _pavlof_rsam_config()
    table = processing.Dr_to_RSAM(100, config=config).set_index("Station")

    # PN7A (~6.8 km) is closer than BLDW (~62 km), so its level is higher.
    assert table.loc["AV.PN7A..BHZ", "RSAM Level"] > table.loc["AV.BLDW..BHZ", "RSAM Level"]


def test_dr_to_rsam_scales_with_reduced_displacement(local_fdsn_client):
    """A larger reduced displacement yields larger RSAM levels at every station."""
    config = _pavlof_rsam_config()
    low = processing.Dr_to_RSAM(50, config=config).set_index("Station")["RSAM Level"]
    high = processing.Dr_to_RSAM(200, config=config).set_index("Station")["RSAM Level"]
    assert (high >= low).all()
    assert (high > low).any()
