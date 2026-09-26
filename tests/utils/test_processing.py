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

TODO: Dr_to_RSAM and eq_picks_to_dataframe both call live FDSN clients for
station responses; they are exercised indirectly by the RSAM integration path
and are candidates for a mocked-client unit test in a later pass.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace, UTCDateTime

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
