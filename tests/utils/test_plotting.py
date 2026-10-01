"""Unit tests for ``volc_alarms.utils.plotting`` (pure geometry/tick math only).

These cover the coordinate/tick helpers that do not render anything to a canvas.
matplotlib already uses the headless "Agg" backend (set on import of the module),
so building a bare Axes to call ``set_time_ticks`` does not open a display or
rasterize a figure.

Covered:
* get_extent         — [lonmin, lonmax, latmin, latmax] centered on a point
* make_path          — a closed matplotlib Path with the expected vertex count
* set_time_ticks     — tick count + format string chosen by window duration
* ShadedReliefESRI._image_url — ArcGIS tile URL assembly
* default_grid_params — base grid style + kwargs merge
* default_colormap   — colormap returned (default + infrasound variant)
* add_watermark      — centered text artist added to the figure
* save_file          — JPG written to TMP_FIGURE_DIR, test-mode watermark
* time_ticks         — x/y limits + formatted date ticks, relative + negative freq

The cartopy ``make_map`` / ``add_volcanoes_to_map`` / ``map_ticks`` gridliner and
the spectrogram builders render real GeoAxes (and ``make_map`` fetches ESRI
tiles); those are exercised by the per-alarm figure tests + integration path, not
re-rendered here.
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


# ---------------------------------------------------------------------------
# ShadedReliefESRI._image_url
# ---------------------------------------------------------------------------
def test_shaded_relief_image_url_builds_esri_tile_path():
    """ShadedReliefESRI._image_url embeds z/y/x into the ArcGIS World_Shaded_Relief URL."""
    tiler = plotting.ShadedReliefESRI()
    url = tiler._image_url((3, 5, 7))  # (x, y, z)
    assert url == (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Shaded_Relief/MapServer/tile/7/5/3.jpg"
    )


# ---------------------------------------------------------------------------
# default_grid_params
# ---------------------------------------------------------------------------
def test_default_grid_params_returns_defaults_and_merges_overrides():
    """default_grid_params returns the base grid style and lets kwargs override it."""
    base = plotting.default_grid_params()
    assert base["ls"] == "--"
    assert base["color"] == "gray"
    assert base["draw_labels"]["bottom"] is True

    overridden = plotting.default_grid_params(color="blue", alpha=0.9)
    assert overridden["color"] == "blue"
    assert overridden["alpha"] == 0.9
    # Untouched defaults survive the merge.
    assert overridden["ls"] == "--"


# ---------------------------------------------------------------------------
# default_colormap
# ---------------------------------------------------------------------------
def test_default_colormap_returns_a_colormap():
    """default_colormap returns a matplotlib LinearSegmentedColormap."""
    from matplotlib.colors import LinearSegmentedColormap

    cmap = plotting.default_colormap()
    assert isinstance(cmap, LinearSegmentedColormap)


def test_default_colormap_infrasound_variant_returns_a_colormap():
    """default_colormap(infrasound=True) also returns a colormap (viridis-based)."""
    from matplotlib.colors import LinearSegmentedColormap

    cmap = plotting.default_colormap(infrasound=True)
    assert isinstance(cmap, LinearSegmentedColormap)


# ---------------------------------------------------------------------------
# add_watermark
# ---------------------------------------------------------------------------
def test_add_watermark_adds_centered_text_to_figure():
    """add_watermark stamps the given text onto the figure as a centered artist."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(4, 4))
    try:
        before = len(fig.texts)
        plotting.add_watermark(fig, "TEST ALARM")
        assert len(fig.texts) == before + 1
        assert fig.texts[-1].get_text() == "TEST ALARM"
    finally:
        plt.close(fig)


# ---------------------------------------------------------------------------
# save_file
# ---------------------------------------------------------------------------
def test_save_file_writes_jpg_named_after_alarm(monkeypatch, tmp_path):
    """save_file writes a JPG into TMP_FIGURE_DIR named from the alarm + timestamp."""
    import matplotlib.pyplot as plt
    from types import SimpleNamespace

    monkeypatch.setenv("TMP_FIGURE_DIR", str(tmp_path))
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    out = plotting.save_file(fig, config, dpi=50)

    assert out.exists()
    assert out.suffix == ".jpg"
    # Spaces in the alarm name become underscores in the filename.
    assert out.name.startswith("Pavlof_RSAM_")


def test_save_file_test_mode_adds_watermark(monkeypatch, tmp_path):
    """save_file stamps a TEST ALARM watermark on the figure when test=True."""
    import matplotlib.pyplot as plt
    from types import SimpleNamespace

    monkeypatch.setenv("TMP_FIGURE_DIR", str(tmp_path))
    fig, ax = plt.subplots()

    captured = {}

    def _watermark(f, text):
        captured["text"] = text

    monkeypatch.setattr(plotting, "add_watermark", _watermark)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    out = plotting.save_file(fig, config, test=True, dpi=50)

    assert captured["text"] == "TEST ALARM"
    assert out.exists()


# ---------------------------------------------------------------------------
# time_ticks (plain axes, no cartopy)
# ---------------------------------------------------------------------------
def test_time_ticks_sets_xaxis_limits_and_labels():
    """time_ticks pins the x-limits and places formatted date ticks on a plain axis."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        plotting.time_ticks(
            ax, "2025-01-01", "2025-01-05", "1D", fmt="%m-%d", axis="x"
        )
        labels = [t.get_text() for t in ax.get_xticklabels()]
        assert "01-01" in labels
        assert "01-05" in labels
    finally:
        plt.close(fig)


def test_time_ticks_relative_seconds_axis():
    """time_ticks with relative=True sets a seconds-based x-limit starting at 0."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        plotting.time_ticks(
            ax, "2025-01-01", "2025-01-02", "6h", relative=True, axis="x"
        )
        left, right = ax.get_xlim()
        assert left == pytest.approx(0.0)
        # One day in seconds.
        assert right == pytest.approx(86400.0)
    finally:
        plt.close(fig)


def test_time_ticks_negative_frequency_counts_back_from_end():
    """time_ticks accepts a negative freq alias, generating ticks from the end backward."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        plotting.time_ticks(
            ax, "2025-01-01", "2025-01-05", "-2D", fmt="%m-%d", axis="y"
        )
        labels = [t.get_text() for t in ax.get_yticklabels()]
        # Counting back by 2 days from the 5th hits the 5th, 3rd, 1st.
        assert "01-05" in labels
        assert "01-03" in labels
    finally:
        plt.close(fig)
