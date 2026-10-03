"""
Figure generation for the Pilot Report (PIREP) alarm.

Builds a location map centered on the pilot report, marks the report position,
overlays nearby volcanoes, and annotates the flight level (title) and pilot
remark (caption), with an orthographic inset for regional context.
"""

from textwrap import wrap

import cartopy.crs as ccrs
import matplotlib.pyplot as plt

from volc_alarms.utils import plotting
from volc_alarms.utils.setup_utils import get_logger

from .detection import get_height_text, get_pilot_remark

logger = get_logger(__name__)


def plot_fig(pirep_row, config, test=False):
    """Build the PIREP location figure.

    Draws a map centered on the report with the report marker, nearby
    volcanoes, a scale bar, and an orthographic inset, titled with the report
    time and flight level and captioned with the pilot remark.

    Parameters
    ----------
    pirep_row : pandas.Series
        A single PIREP report row exposing ``lat``, ``lon``, ``time``, ``FL``,
        and ``REPORT``.
    config : object
        PIREP alarm configuration (map distances, volcano overlay, output).
    test : bool, optional
        Save with the test watermark/path when True, by default False.

    Returns
    -------
    pathlib.Path
        Path to the saved figure.
    """
    fig, ax = plt.subplots(figsize=(3.4, 3.15))

    X_DIST = getattr(config, "map_xdist", 300)
    Y_DIST = getattr(config, "map_ydist", 300)
    ax, extent = plotting.make_map(
        ax, pirep_row.lat, pirep_row.lon, xdist=X_DIST, ydist=Y_DIST, basemap="highres"
    )
    plotting.map_ticks(ax, extent, grid_kwargs="default")
    plotting.add_scale_bar(ax, 50, txt_yoffset=0.01, extent=extent)

    plotting.add_volcanoes_to_map(ax, extent, config)
    ax.plot(
        pirep_row.lon,
        pirep_row.lat,
        "o",
        mec="k",
        ms=6,
        mfc="gold",
        mew=0.5,
        transform=ccrs.Geodetic(),
    )

    # Write title & caption
    t0 = pirep_row.time.strftime("%Y-%m-%d %H:%M")
    ax.set_title(f"{t0}\n{get_height_text(pirep_row.FL)}", fontsize=8)
    xlabel_text = "\n".join(wrap(get_pilot_remark(pirep_row.REPORT), 50))
    xlabel_text = "\n".join(wrap(xlabel_text, 50))
    xlabel_text = f"Pilot Remark: {xlabel_text}"
    ax.text(0.5, -0.08, xlabel_text, va='top', ha='center',
        rotation='horizontal', rotation_mode='anchor',
        transform=ax.transAxes, fontsize=6)

    ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
    ax_inset, _inset_extent = plotting.make_map(
        ax_inset,
        pirep_row.lat,
        pirep_row.lon,
        xdist=800,
        ydist=600,
        basemap="land",
        projection="orthographic",
        water_color="white",
    )

    plotting.add_inset_polygon(ax_inset, extent)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=300)

    return jpg_file
