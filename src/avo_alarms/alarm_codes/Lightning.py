import os
import traceback
import warnings

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import date2num
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from avo_alarms.utils import messaging, plotting, processing, downloading, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

warnings.filterwarnings("ignore")
logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    ### get alerts from volcview api
    strokes_df = downloading.download_lightning(force=force_flag)
    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    T1 = pd.to_datetime(T0_str) - pd.to_timedelta(config.duration, "s")

    if strokes_df is None:
        logger.error("Error downloading lightning data from API")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Error getting data from Volcview-API"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    if len(strokes_df) == 0:
        logger.info("No new lightning strokes detected")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new strokes detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    strokes_df = strokes_df[strokes_df["time"] > T1.strftime("%Y-%m-%d %H:%M:%S")]

    if test_flag:
        strokes_df["v_distance"] = strokes_df["api_vdist"]
        strokes_df["v_name"] = strokes_df["api_vname"]
    else:
        volcs = load_volcano_list()
        volcs = volcs[volcs["Lightning"] == "Y"]
        strokes_df = processing.find_nearest_volcano(
            strokes_df,
            volc_df=volcs,
        )

    strokes_df = strokes_df[strokes_df["v_distance"] < config.dist2]
    new_strokes_df, strokes_df = alarming.filter_dataframe(strokes_df, id_column="id", test=test_flag)
    logger.info(
        f"{len(new_strokes_df)} new and {len(strokes_df) - len(new_strokes_df)} old strokes detected."
    )

    if len(new_strokes_df) == 0:
        logger.info("No lightning detected")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new strokes detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    volcanoes = new_strokes_df.v_name.unique()
    if force_flag:
        volcanoes = [volcanoes[0]]
    N_v = len(volcanoes)
    logger.info(f"Lightning detected at {N_v:.0f} volcano{'' if N_v==1 else 'es'}")
    for v_name in volcanoes:
        if not v_name:
            logger.warning("Null volcano. Skipping...")
            continue

        logger.info(f"--- Processing detects at {v_name} volcano ---")
        v_strokes = strokes_df[strokes_df["v_name"] == v_name]
        new_v_strokes, v_strokes = alarming.filter_dataframe(v_strokes, id_column="id", test=test_flag)
        n_ring1, n_ring2 = inner_outer(new_v_strokes, config)

        if len(new_v_strokes) == 0:
            logger.info("Old detection already processed")
            state = "WARNING"
            state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)
        else:
            logger.info("**** NEW DETECTION")
            new_v_strokes = new_v_strokes.sort_values("time")
            logger.info(
                f"{len(new_v_strokes)} new and {len(v_strokes) - len(new_v_strokes)} old strokes detected."
            )
            if new_v_strokes.iloc[0].v_distance > config.dist1:
                logger.info("...distal detection 1st.")
                state = "WARNING"
                state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)
            else:
                logger.info('**** PROXIMAL DETECTION 1st')
                state = "CRITICAL"
                state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)

                ### Send Email Notification ####
                logger.info("Crafting message...")
                subject, message = create_message(new_v_strokes, v_strokes)
                try:
                    filename = plot_fig(v_strokes, config, T0, test=test_flag)
                except Exception as e:
                    logger.error("Error generating figure...")
                    logger.error(e)
                    logger.error(traceback.format_exc())
                    filename = None

                try:
                    logger.info("Sending message to mattermost")
                    mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
                    message = f"{message}\n\n{mm_url}"
                except Exception as e:
                    logger.error("problem posting to mattermost")
                    logger.error(e)
                    logger.error(traceback.format_exc())

                messaging.send_alert(
                    config.alarm_name,
                    subject,
                    message,
                    attachment=filename,
                    test=test_flag,
                )
                alarming.record_send(
                    config,
                    T0,
                    volcano=new_v_strokes.iloc[0].v_name,
                    event_id=new_v_strokes.id.to_list(),
                    test=test_flag,
                )
                # delete the file you just sent
                if filename:
                    os.remove(filename)

    messaging.icinga(config, state, state_message, send=icinga_flag)


def inner_outer(df, config):

    n_ring1 = len(df[df["v_distance"] < config.dist1])
    n_ring2 = len(df) - n_ring1

    return n_ring1, n_ring2


def get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config):
    match state:
        case "WARNING":
            if n_ring1 + n_ring2 == 0:
                state_message = f"{T0_str} (UTC) {v_name} Lightning Detection!"
            else:
                state_message = f"{T0_str} (UTC) {v_name} Distal Lightning Detection!"
        case "CRITICAL":
            state_message = f"{T0_str} (UTC) {v_name} Lightning Detection!"
            state_message = f"{state_message} {n_ring1 + n_ring2} new strokes!"

    d1 = config.dist1
    d2 = config.dist2
    state_message = f"{state_message} {n_ring1} strokes < {d1:g} km ({d1:g} km < {n_ring2} < {d2:g} km)"
    state_message = f"{state_message} in past {config.duration/60:.0f} minutes."

    return state_message


def get_direction(azimuth):
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    ix = int(np.round(azimuth / (360 / len(dirs))))

    return dirs[ix % len(dirs)]


def create_message(df_new, df_recent):

    v_last = df_recent.iloc[-1]
    v_name = v_last.v_name
    subject = f"--- {v_name} Lightning ---"


    if len(df_new) == 1:
        message = f"\n{len(df_new)} new stroke! ({len(df_recent)} total)"
    else:
        message = f"\n{len(df_new)} new strokes! ({len(df_recent)} total)"

    message = f"{message}\n\n-- Most recent --"
    t = utc(df_recent.iloc[0].time)
    message = f"{message}\n{messaging.format_timestring(t)}"

    dist = v_last.v_distance
    _, az1, _ = gps2dist_azimuth(v_last.api_vlat, v_last.api_vlon, v_last.latitude, v_last.longitude)
    direction = get_direction(az1)
    message = f"{message}\n{dist:.0f} km {direction} of {v_name},"
    network_txt = ", ".join(df_new.dataSource.unique()).replace("EN", "Earth Networks")
    message = f"{message}\n\nData source: {network_txt}"

    return subject, message


def plot_fig(df, config, T0, test=False):
    
    fig, ax = plt.subplots(figsize=(3.4, 3.15))

    lat0 = df.iloc[0].api_vlat
    lon0 = df.iloc[0].api_vlon
    v_name = df.iloc[0].v_name
    t_recent = df.iloc[0].time.strftime('%Y-%m-%d %H:%M:%S')

    X_DIST = getattr(config, "dist2", 100)
    Y_DIST = getattr(config, "dist2", 100)
    
    ax, extent = plotting.make_map(ax, lat0, lon0, basemap="HIGHRES", xdist=X_DIST, ydist=Y_DIST)
    ax.set_title(f"--- {v_name} Lightning ---\n{t_recent} UTC", fontsize=8)
    plotting.map_ticks(ax, extent, grid_kwargs="default")
    plotting.add_volcanoes_to_map(ax, extent, config, c1="k", c2="grey", linewidths=0.1)
    ax.plot(lon0, lat0, "^", mfc="k", mec="w", ms=6, transform=ccrs.Geodetic())
    plotting.add_scale_bar(ax, 15, txt_yoffset=0.01)

    map_hdl = ax.scatter(df.longitude.values,
                            df.latitude.values,
                            s=14,
                            c=date2num(df.time),
                            cmap="plasma",
                            vmin=date2num((T0-config.duration).datetime), 
                            vmax=date2num(T0.datetime),
                            ec="k",
                            lw=0.2,
                            transform=ccrs.Geodetic(),
                            zorder=1e5)

    cbaxes = inset_axes(ax, height="70%", width="4%", loc=6, borderpad=-1)
    cbar = plt.colorbar(map_hdl, cax=cbaxes, orientation="vertical")
    cbaxes.yaxis.set_ticks_position("left")
    cbar.set_ticks([date2num((T0-config.duration).datetime), date2num(T0.datetime)])
    cbar.set_ticklabels([f"{config.duration / 60:.0f}\nmin\nago", "Now"])
    cbar.ax.tick_params(labelsize=6)

    ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
    ax_inset, inset_extent = plotting.make_map(ax_inset, lat0, lon0,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_volcanoes_to_map(ax_inset, inset_extent, config, s1=7, s2=4, linewidths=0.1)
    plotting.add_inset_polygon(ax_inset, extent)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=300)

    return jpg_file