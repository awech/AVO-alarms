import os

import cartopy
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.dates import date2num
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from obspy import Catalog

from volc_alarms.utils import downloading, plotting, processing
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def make_figure(swarm, T0, config, test=False):

    fig, ax = plt.subplot_mosaic(
        [["map"], ["stem"]],
        figsize=(4, 5.5),
        height_ratios=[3, 1],
        layout="constrained",
    )

    lat0 = swarm.latitude.mean()
    lon0 = swarm.longitude.mean()

    #################### Add main map ####################
    ax["map"], extent = plotting.make_map(
        ax["map"],
        lat0,
        lon0,
        basemap="hillshade",
        xdist=getattr(config, "map_distance", 50),
        ydist=getattr(config, "map_distance", 50)
    )
    plotting.map_ticks(ax["map"], extent, grid_kwargs="default", y_rotate=90)
    ax["map"].tick_params(length=0)
    plotting.add_volcanoes_to_map(ax["map"], extent, config)
    plotting.add_scale_bar(ax["map"], 10, txt_yoffset=0.01, extent=extent)

    try:
        logger.info("Downloading stations that have picks")
        CAT = Catalog()
        for i, row in swarm.iterrows():
            evt_url = f"{os.getenv('FDSN_URL')}eventid={row.id}"
            CAT += downloading.download_hypocenter_xml(evt_url)
        CAT = processing.addPhaseHint(CAT)
        channels = processing.eq_picks_to_dataframe(CAT)

        ax["map"].plot(
            channels.Longitude,
            channels.Latitude,
            "s",
            mfc="dimgrey",
            ms=4,
            mec="k",
            mew=0.6,
            transform=cartopy.crs.PlateCarree(),
        )
    except Exception as e:
        logger.warning("Problem downloading station info")
        logger.error(e)
        logger.warning("Skip plotting stations on map.")


    ################### Add inset map ###################
    logger.info('Plotting inset map...')
    ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
    ax_inset, inset_extent = plotting.make_map(ax_inset, lat0, lon0,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_inset_polygon(ax_inset, extent)


    ################### Make stem plot ###################
    swarm = swarm.sort_values("time")
    time = date2num(swarm.time)
    map_hdl = ax["map"].scatter(
        swarm.longitude.values,
        swarm.latitude.values,
        s=40,
        c=time,
        cmap="plasma",
        vmin=date2num((T0 - swarm.iloc[0].param_duration).datetime),
        vmax=date2num(T0.datetime),
        marker="o",
        edgecolors="k",
        linewidth=0.5,
        transform=cartopy.crs.PlateCarree(),
        zorder=1e4,
    )

    mag_swarm = swarm[~swarm["mag"].isnull()]
    time = date2num(mag_swarm.time)
    markerline, stemlines, baseline = ax["stem"].stem(
        mag_swarm.time,
        mag_swarm.mag,
        linefmt="k-",
        markerfmt="k.",
        bottom=-5,
    )
    stemlines.set_linewidth(0.8)
    ax["stem"].scatter(
        mag_swarm.time,
        mag_swarm.mag,
        s=30,
        c=time,
        edgecolors="k",
        linewidth=0.8,
        cmap="plasma",
        vmin=date2num((T0 - swarm.iloc[0].param_duration).datetime),
        vmax=date2num(T0.datetime),
        zorder=10,
        clip_on=False,
        label="_nolegend_",
    )
    ax["stem"].set_ylim(mag_swarm.mag.min() - 0.2, mag_swarm.mag.max() + 0.2)

    no_mag_swarm = swarm[swarm["mag"].isnull()]
    time = date2num(no_mag_swarm.time)
    ax["stem"].scatter(
        no_mag_swarm.time,
        np.ones_like(time) * ax["stem"].get_ylim()[0],
        s=30,
        c="gray",
        edgecolors="k",
        linewidth=0.8,
        zorder=10,
        clip_on=False,
        label="No magnitude",
    )

    T1 = T0 - swarm.iloc[0].param_duration
    T2 = T0
    duration = swarm.iloc[0].param_duration
    match duration:
        case val if val <= 3600:
            dt = "-10min"
        case val if 3600 < val < 4*3600:
            dt = "-30min"
        case val if 4*3600 <= val < 12*3600:
            dt = "-1h"
        case val if val >= 12*3600:
            dt = "-4h"

    plotting.time_ticks(ax["stem"], T1.datetime, T2.datetime, dt, fmt="%Y-%m-%d\n%H:%M", fontsize=6, rotation_mode="anchor")
    ax["stem"].tick_params(axis="x", which="major", pad=0)
    ax["stem"].set_ylabel("Magnitude", fontsize=8)
    ax["stem"].grid(axis="both", linewidth=0.2, linestyle="--")

    if len(no_mag_swarm) > 0:
        ax["stem"].legend(loc="upper right", markerscale=0.8, fontsize=6)


    ################### Add colorbar ###################
    cbaxes = inset_axes(ax["map"], height="70%", width="4%", loc=6, borderpad=-1)
    cbar = plt.colorbar(map_hdl, cax=cbaxes, orientation="vertical")
    cbaxes.yaxis.set_ticks_position("left")
    cbar.set_ticks([date2num((T0-config.DURATION).datetime), date2num(T0.datetime)])
    h = np.floor(config.DURATION / 3600)
    m = (config.DURATION/3600 - h) * 60
    min_txt = f"\n{m:g} mins" if m > 0 else ""
    ctick_lab = f"{h:g} hrs" + min_txt +"\nago"
    cbar.set_ticklabels([ctick_lab, "Now"])
    cbar.ax.tick_params(labelsize=6)

    N_evt = len(swarm)
    volcano = swarm.iloc[0].v_name
    T1 = swarm.time.min().strftime('%Y-%m-%d %H:%M')
    T2 = swarm.time.max().strftime('%Y-%m-%d %H:%M')
    ax["map"].set_title(
        f"{N_evt} events at {volcano}\nFirst:     {T1} UTC\nLatest:  {T2} UTC",
        fontsize=8,
    )

    jpg_file = plotting.save_file(fig, config, dpi=250, test=test)
    plt.close(fig)

    return jpg_file
