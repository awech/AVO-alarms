import matplotlib.pyplot as plt
import numpy as np
from cartopy import crs as ccrs
from obspy import UTCDateTime

from avo_alarms.utils import plotting
from avo_alarms.utils.setup_utils import get_logger

from .detection import get_extent, process_polygons, text_to_latlon

logger = get_logger(__name__)


def make_map(vaa, config, test=False):

    lons_0, lats_0, level_0 = process_polygons(vaa, "OBS VA CLD")
    lons_6, lats_6, level_6 = process_polygons(vaa, "FCST VA CLD +6HR")
    lons_12, lats_12, level_12 = process_polygons(vaa, "FCST VA CLD +12HR")
    lons_18, lats_18, level_18 = process_polygons(vaa, "FCST VA CLD +18HR")

    LONS = np.concatenate((lons_0, lons_6, lons_12, lons_18))
    LATS = np.concatenate((lats_0, lats_6, lats_12, lats_18))
    LEVELS = np.array([level_0, level_6, level_12, level_18])

    n_levels = len(np.unique(LEVELS[LEVELS != ""]))

    if len(LONS) == 0 or len(LATS) == 0:
        logger.warning("No polygons to plot. Not generating figure.")
        return []

    v_lat, v_lon = text_to_latlon(vaa['PSN'])
    LONS = np.append(LONS, v_lon)
    LATS = np.append(LATS, v_lat)
    extent = get_extent(LONS, LATS)

    fig, ax = plt.subplots(figsize=(3.5, 3.5), layout="constrained")

    ax, extent = plotting.make_map(
        ax, v_lat, v_lon, basemap="land", extent=extent, projection="orthographic"
    )
    ax.coastlines(lw=0.2)

    plotting.map_ticks(ax, extent, grid_kwargs="default")
    ax.plot(v_lon, v_lat, "^", mfc="k", mec="w", ms=6, transform=ccrs.Geodetic())

    t_form = ccrs.PlateCarree()
    if lons_0:
        lvl_txt = f"\n({level_0:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_0, lats_0, '-', c='firebrick', lw=1.5, label=f'Observed{lvl_txt}', transform=t_form, zorder=100)
    if lons_6:
        lvl_txt = f"\n({level_6:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_6, lats_6, '--', c='orangered', lw=1.25, label='6H Forecast', transform=t_form, zorder=99)
    if lons_12:
        lvl_txt = f"\n({level_12:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_12, lats_12, '--', c='orange', lw=1, label='12H Forecast', transform=t_form, zorder=98)
    if lons_18:
        lvl_txt = f"\n({level_18:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_18, lats_18, '-.', c='goldenrod', lw=0.75, label='18H Forecast', transform=t_form, zorder=97)


    ax.legend(fontsize=6, loc='lower left')

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    vaa_time = UTCDateTime(vaa["DTG"]).strftime("%Y-%m-%d %H:%M")

    ax.set_title(
        f"{volcano_name} VAA\n{level_0}\n{vaa_time}", fontsize=10
    )
    plt.tight_layout()

    logger.info("Saving figure...")
    jpg_file = plotting.save_file(fig, config, dpi=300, test=test)
    plt.close(fig)

    return jpg_file
