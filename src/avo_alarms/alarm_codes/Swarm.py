import os
import traceback
from itertools import combinations

import cartopy
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import utm
from matplotlib.dates import date2num
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from obspy import Catalog
from sklearn.cluster import DBSCAN

from avo_alarms.utils import downloading, messaging, plotting, processing
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    # Download the event data
    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    outfile_cols = ["id", "time", "latitude", "longitude", "depth", "mag", "v_name"]

    config.DURATION = np.array([swm['MAX_EVT_TIME'] for swm in config.swarm_parameters]).max()
    logger.info(f"Downloading events {config.DURATION:g}s before {T0_str}")
    URL = build_download_url(T0, config)
    T_min = (T0 - config.DURATION).strftime("%Y-%m-%d %H:%M:%S")
    eq_df = downloading.download_hypocenters_csv(URL)

    # Error pulling events
    if eq_df is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) FDSN connection error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Filter out regional events
    logger.info(f"{len(eq_df):g} earthquakes detected")
    logger.info("Filtering out regional VTs")
    eq_df = processing.find_nearest_volcano(eq_df)
    eq_df = eq_df[eq_df["v_distance"] < config.VOLCANO_DISTANCE]
    logger.info(f"{len(eq_df):g} earthquakes near volcanoes")

    # No quakes close enough to volcanoes
    if len(eq_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new swarm activity"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Read in old events. Filter to new events
    new_eq_df, eq_df = processing.compare_to_old_events(
        eq_df, config.outfile, outfile_cols, "id"
    )
    old_eq_df = pd.read_csv(config.outfile, parse_dates=["time"])

    # No new earthquakes
    if len(new_eq_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Check for swarms
    logger.info("Clustering...")
    swarms = get_swarms(new_eq_df, T0, config)
    swarm_continue = check_swarm_continue(T0, config, old_eq_df, new_eq_df)

    # New earthquakes, but not swarm-y
    if len(swarms) == 0 and len(swarm_continue) == 0:
        logger.warning("Earthquakes detected, but no new swarm actvity")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new swarm actvity"

        # No new events to write
        out_df = old_eq_df

    # New earthquakes aren't swarm-y by themselves, but continuation of ongoing swarm
    elif len(swarms) == 0 and len(swarm_continue) > 0:
        logger.info("Earthquakes detected. Continuation of swarm actvity")
        state = "WARNING"
        v_list = [swarm.iloc[0].v_name for swarm in swarm_continue]
        v_list_txt = ", ".join(np.unique(v_list))
        state_message = f"{T0_str} (UTC) Ongoing swarm actvity at: {v_list_txt}"

        # Merge new and old swarm detects
        merged_swarm = pd.concat(swarm_continue, keys="id", ignore_index=True).drop_duplicates("id")
        out_df = pd.concat([old_eq_df, merged_swarm], keys="id", ignore_index=True).drop_duplicates("id")

    else:
        # remove duplicate or overlapping swarms
        swarms = compare_swarms(swarms)

        for swarm in swarms:
            state = "CRITICAL"
            volcano = swarm.iloc[0].v_name
            state_message = f"{T0_str} (UTC) Swarm actvity at: {volcano}"

            subject, message = create_message(swarm)
            logger.info(subject)
            logger.info(message)

            #### Generate Figure ####
            try:
                filename = make_figure(swarm, T0, config, test=test_flag)
                swarm_t1 = swarm.time.min().strftime("%Y%m%d_%H%M")
                swarm_t2 = swarm.time.max().strftime("%Y%m%d_%H%M")
                new_filename = f"{volcano}_M{swarm_t1}-{swarm_t2}.png"
                filename = filename.rename(filename.parent / new_filename)
            except Exception as e:
                filename = []
                logger.error("Problem making figure. Continue anyway")
                logger.warning(e)
                logger.warning(traceback.format_exc())

            if test_flag:
                messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

            logger.info("Posting message to Mattermost...")
            messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag, volcano=volcano)

            if filename:
                os.remove(filename)

        # Merge new and old swarm detects
        merged_swarm = pd.concat(swarms, keys="id", ignore_index=True).drop_duplicates("id")
        out_df = pd.concat([old_eq_df, merged_swarm], keys="id", ignore_index=True).drop_duplicates("id")


    out_df = out_df[out_df["time"] > T_min]
    out_df = out_df.sort_values("time")
    processing.write_to_csv(out_df, config, outfile_cols)
    messaging.icinga(config, state, state_message, send=icinga_flag)
    
    return


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


def create_message(swarm):

    tmin = pd.Timestamp(swarm.time.min(), tz="UTC")
    tmax = pd.Timestamp(swarm.time.max(), tz="UTC")
    dt = tmax - tmin
    hours = np.floor(dt.total_seconds() / 3600)
    minutes = np.round((dt.total_seconds() - hours * 3600) / 60)

    message = f"{len(swarm)} events in {hours:.0f}h {minutes:.0f}m"
    message += "\n\n***--- UTC ---***"
    message += f"\n**First:** {tmin.strftime('%Y-%m-%d %H:%M')}"
    message += f"\n**Last:** {tmax.strftime('%Y-%m-%d %H:%M')}"

    tmin_local = tmin.tz_convert(os.environ["TIMEZONE"])
    tmax_local = tmax.tz_convert(os.environ["TIMEZONE"])

    message += f"\n\n***--- {tmax_local.tzname()} ---***"
    message += f"\n**First:** {tmin_local.strftime('%Y-%m-%d %H:%M')}"
    message += f"\n**Last:** {tmax_local.strftime('%Y-%m-%d %H:%M')}"

    message += f"\n\n**Magnitude range:** {swarm.mag.min():.1f} - {swarm.mag.max():.1f}"
    num_nan_mags = len(np.where(np.isnan(swarm.mag))[0])
    if num_nan_mags == 1:
        message += f" ({num_nan_mags:.0f} event with unassigned magnitude)"
    elif num_nan_mags > 1:
        message += f" ({num_nan_mags:.0f} events with unassigned magnitude)"

    message += (
        f"\n**Depth range:** {swarm.depth.min():.1f} - {swarm.depth.max():.1f} km"
    )
    num_nan_deps = len(np.where(np.isnan(swarm.depth))[0])
    if num_nan_deps == 1:
        message += f" ({num_nan_deps:.0f} event with unassigned depth)"
    elif num_nan_deps > 1:
        message += f" ({num_nan_deps:.0f} events with unassigned depth)"

    subject = f"Earthquake swarm at {swarm.iloc[0].v_name}"

    return subject, message


def build_download_url(T0, config):

    T2 = T0
    T1 = T2 - config.DURATION
    URL = (
        f"{os.environ['FDSN_URL']}"
        f"starttime={T1.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&endtime={T2.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&maxdepth={config.MAXDEP}"
        "&format=csv"
    )
    return URL


def check_swarm_continue(T0, config, old_eq_df, new_eq_df):

    all_eq_df = pd.concat(
        [old_eq_df, new_eq_df], keys="id", ignore_index=True
    ).drop_duplicates("id")
    swarm_continue = get_swarms(all_eq_df.copy(), T0, config)
    swarm_continue = [swarm.loc[~swarm["id"].isin(old_eq_df.id)] for swarm in swarm_continue]
    swarm_continue = [swarm for swarm in swarm_continue if len(swarm)>0]

    return swarm_continue


def compare_swarms(swarms):
    flag = True
    test_swarms = swarms.copy()
    while flag:
        SWARM_COMBOS = list(combinations(range(len(test_swarms)), 2))

        if len(SWARM_COMBOS) > 0:
            remove_swarm_ind = []
            flag_list = []
            for ind_combo in SWARM_COMBOS:
                # check for duplicate swarm detections
                if test_swarms[ind_combo[0]].equals(test_swarms[ind_combo[1]]):
                    logger.info("found equals")
                    flag_list.append(True)
                    remove_swarm_ind.append(ind_combo[0])
                    continue

                # check for overlap, and keep the shortest duration event
                int_df = pd.merge(
                    test_swarms[ind_combo[0]],
                    test_swarms[ind_combo[1]],
                    how="inner",
                    on=["id", "id"],
                )
                if len(int_df) > 0:
                    logger.info("overlap")
                    dt0 = (
                        test_swarms[ind_combo[0]].Time.max()
                        - test_swarms[ind_combo[0]].Time.min()
                    )
                    dt1 = (
                        test_swarms[ind_combo[1]].Time.max()
                        - test_swarms[ind_combo[1]].Time.min()
                    )
                    remove_swarm_ind.append(ind_combo[np.argmax([dt0, dt1])])
                    flag_list.append(True)
                else:
                    logger.info("no overlap")
                    flag_list.append(False)

            # update swarms list with duplicate/overlapping swarms removed
            test_swarms = [
                test_swarms[x]
                for x in range(len(test_swarms))
                if x not in remove_swarm_ind
            ]
            flag = any(flag_list)
        else:
            flag = False

    return test_swarms


def get_swarms(df, T0, config):

    t_str_fmt = "%Y-%m-%d %H:%M:%S"
    lat0 = df.latitude.mean()
    lon0 = df.longitude.mean()
    ZN_LET = utm.latitude_to_zone_letter(lat0)
    ZN_NUM = utm.latlon_to_zone_number(lat0, lon0)

    east, north, *_ = utm.from_latlon(
        df.latitude, df.longitude, force_zone_number=ZN_NUM, force_zone_letter=ZN_LET
    )
    df["x"] = east / 1000
    df["y"] = north / 1000

    SWARMS = []
    for params in config.swarm_parameters:
        # scale time to match distance
        cat_df = df.copy()[df["time"] > (T0 - params["MAX_EVT_TIME"]).strftime(t_str_fmt)]
        if len(cat_df) == 0:
            continue
        t = cat_df.time
        dtime = np.array([(t0 - t.min()).total_seconds() for t0 in t])
        dtime = dtime * (params["MAX_EVT_DISTANCE"] / float(params["MAX_EVT_TIME"]))
        # put distance and time together
        X = np.array([cat_df["x"], cat_df["y"], dtime]).T
        db = DBSCAN(
            eps=params["MAX_EVT_DISTANCE"], min_samples=params["MIN_NUM_EVT"]
        ).fit(X)

        cat_df.loc[:, "label"] = db.labels_
        cat_df.loc[:, "param_duration"] = float(params["MAX_EVT_TIME"])
        all_detects = cat_df[cat_df["label"] > -1]
        # NOISE = cat_df[cat_df['label']==-1]

        for i in all_detects.label.unique():
            df = cat_df[cat_df["label"] == i]
            SWARMS.append(df.copy())

    return SWARMS