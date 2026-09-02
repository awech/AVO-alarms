import matplotlib.pyplot as plt
import numpy as np
from cartopy import crs as ccrs
from obspy import UTCDateTime

from volc_alarms.utils import plotting
from volc_alarms.utils.setup_utils import get_logger

from .detection import get_extent, process_polygons, text_to_latlon

logger = get_logger(__name__)


def make_map(vaa, config, test=False):

    # process_polygons now returns a LIST of (lons, lats, level_txt) rings per
    # field (possibly empty). Each field gets its own plot style, and each ring
    # of a field is plotted as its own line so distinct rings are not joined by
    # a spurious connecting segment.
    groups_0 = process_polygons(vaa, "OBS VA CLD")
    groups_6 = process_polygons(vaa, "FCST VA CLD +6HR")
    groups_12 = process_polygons(vaa, "FCST VA CLD +12HR")
    groups_18 = process_polygons(vaa, "FCST VA CLD +18HR")

    # Style per field: (linestyle, color, linewidth, zorder, legend label).
    fields = [
        (groups_0, '-', 'firebrick', 1.5, 100, 'Observed'),
        (groups_6, '--', 'orangered', 1.25, 99, '6H Forecast'),
        (groups_12, '--', 'orange', 1, 98, '12H Forecast'),
        (groups_18, '-.', 'goldenrod', 0.75, 97, '18H Forecast'),
    ]

    # Union of every ring's coordinates across all fields, for extent.
    LONS = np.concatenate(
        [np.array(lons) for groups, *_ in fields for lons, lats, level_txt in groups]
        or [np.array([])]
    )
    LATS = np.concatenate(
        [np.array(lats) for groups, *_ in fields for lons, lats, level_txt in groups]
        or [np.array([])]
    )

    if len(LONS) == 0 or len(LATS) == 0:
        logger.warning("No polygons to plot. Not generating figure.")
        return []

    # Parse the volcano PSN defensively. A malformed / out-of-range upstream
    # coordinate (e.g. a 7-char longitude that text_to_latlon reads as -1540.95)
    # must not be allowed to flow into get_extent / the orthographic projection
    # center, where it crashes cartopy with "Axis limits cannot be NaN or Inf".
    # Treat the PSN as usable only if it parses AND is in range.
    psn_ok = False
    v_lat = v_lon = None
    try:
        v_lat, v_lon = text_to_latlon(vaa['PSN'])
        psn_ok = -90 <= v_lat <= 90 and -180 <= v_lon <= 180
    except (ValueError, IndexError, TypeError):
        psn_ok = False

    if psn_ok:
        LONS = np.append(LONS, v_lon)
        LATS = np.append(LATS, v_lat)
        center_lat, center_lon = v_lat, v_lon
    else:
        logger.warning(
            f"Volcano PSN {vaa.get('PSN')!r} could not be used; centering map on "
            "polygon centroid and skipping volcano marker."
        )
        # Center on the polygon-only coordinates so the figure still renders.
        center_lat = float(np.mean(LATS))
        center_lon = float(np.mean(LONS))

    extent = get_extent(LONS, LATS)

    fig, ax = plt.subplots(figsize=(3.5, 3.5), layout="constrained")

    ax, extent = plotting.make_map(
        ax, center_lat, center_lon, basemap="land", extent=extent,
        projection="orthographic"
    )
    ax.coastlines(lw=0.2)

    plotting.map_ticks(ax, extent, grid_kwargs="default")
    if psn_ok:
        ax.plot(v_lon, v_lat, "^", mfc="k", mec="w", ms=6, transform=ccrs.Geodetic())

    t_form = ccrs.PlateCarree()
    # Plot each ring of each field separately. Only the first ring of a field
    # carries the field's legend label; subsequent rings use '_nolegend_' so the
    # legend shows a single entry per field. The per-label ":,g asl" annotation
    # from the old numeric-level model is dropped (it broke on the new string
    # level_txt); level info now lives in the title instead.
    for groups, style, color, lw, zorder, field_label in fields:
        for j, (lons, lats, level_txt) in enumerate(groups):
            label = field_label if j == 0 else '_nolegend_'
            ax.plot(
                lons, lats, style, c=color, lw=lw, label=label,
                transform=t_form, zorder=zorder,
            )

    ax.legend(fontsize=6, loc='lower left')

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    vaa_time = UTCDateTime(vaa["time"]).strftime("%Y-%m-%d %H:%M")

    # Title lists all DISTINCT OBS ring levels, comma-separated (skip empties),
    # preserving insertion order.
    obs_levels = []
    for lons, lats, level_txt in groups_0:
        if level_txt and level_txt not in obs_levels:
            obs_levels.append(level_txt)
    levels = ", ".join(obs_levels)

    ax.set_title(
        f"{volcano_name} VAA\n{levels}\n{vaa_time}", fontsize=10
    )
    plt.tight_layout()

    logger.info("Saving figure...")
    jpg_file = plotting.save_file(fig, config, dpi=300, test=test)
    plt.close(fig)

    return jpg_file
