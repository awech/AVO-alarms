"""Unit tests for ``volc_alarms.utils.plotting`` (pure geometry/tick math only).

These cover the coordinate/tick helpers that do not render anything to a canvas.
matplotlib already uses the headless "Agg" backend (set on import of the module),
so building a bare Axes to call ``set_time_ticks`` does not open a display or
rasterize a figure.

Covered:
* get_extent      — [lonmin, lonmax, latmin, latmax] centered on a point
* make_path       — a closed matplotlib Path with the expected vertex count
* set_time_ticks  — tick count + format string chosen by window duration

TODO: the cartopy ``make_map`` / spectrogram builders render real axes and are
covered by the per-alarm figure tests and the integration path, not here.
"""

from __future__ import annotations

import numpy as np
import pytest

from volc_alarms.utils import plotting

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# get_extent
# ---------------------------------------------------------------------------
def test_get_extent_centers_bounds_on_point():
    """get_extent returns bounds centered on (lon0, lat0) with lat spanning ~ydist."""
    lat0, lon0 = 55.0, -160.0
    lonmin, lonmax, latmin, latmax = plotting.get_extent(lat0, lon0, xdist=25, ydist=25)

    # Center is preserved.
    assert (lonmin + lonmax) / 2 == pytest.approx(lon0)
    assert (latmin + latmax) / 2 == pytest.approx(lat0)
    # Latitude half-span is (ydist/2)/111.1 degrees.
    assert (latmax - latmin) == pytest.approx((25 / 111.1))
    # Longitude span is wider than latitude span at high latitude (cos factor).
    assert (lonmax - lonmin) > (latmax - latmin)


# ---------------------------------------------------------------------------
# make_path
# ---------------------------------------------------------------------------
def test_make_path_returns_closed_path_with_expected_vertices():
    """make_path builds a matplotlib Path tracing the four extent edges (4*n verts)."""
    extent = [-161.0, -160.0, 54.0, 55.0]
    path = plotting.make_path(extent)

    # Four edges of n=20 samples each.
    assert path.vertices.shape == (80, 2)
    # Every vertex lies within the extent box.
    lons, lats = path.vertices[:, 0], path.vertices[:, 1]
    assert lons.min() == pytest.approx(extent[0])
    assert lons.max() == pytest.approx(extent[1])
    assert lats.min() == pytest.approx(extent[2])
    assert lats.max() == pytest.approx(extent[3])


# ---------------------------------------------------------------------------
# set_time_ticks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "duration, expected_fmt, expected_nticks",
    [
        (3600, "%H:%M", 7),          # hour-class window
        (600, "%H:%M", 6),           # 5-min multiple below an hour
        (1234, "%H:%M:%S", 6),       # odd duration -> seconds format
    ],
)
def test_set_time_ticks_selects_format_and_tick_count(duration, expected_fmt, expected_nticks):
    """set_time_ticks picks the tick format + count from the window duration."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        fmt = plotting.set_time_ticks(ax, 0, duration, duration)
        assert fmt == expected_fmt
        assert len(ax.get_xticks()) == expected_nticks
    finally:
        plt.close(fig)
