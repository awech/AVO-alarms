# Lightning alarm based on WWLLN & Earth Networks data
#
# Wech 2020-04-09

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

from avo_alarms.utils import messaging, plotting, processing
from avo_alarms.utils.setup_utils import get_logger

warnings.filterwarnings("ignore")
logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    ### get alerts from volcview api
    A = processing.download_lightning()
    t_string = T0.strftime("%Y-%m-%d %H:%M")

    if A is None:
        state = "WARNING"
        state_message = f"{t_string} (UTC) Error getting data from Volcview-API"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    ignored_volcanoes = []

    if len(A) > 0:
        A["send_alert"] = False
        A["nearestVnum"] = A["nearestVnum"].astype("int")

        # Limit strokes to those in AVO's file list
        VOLCS = pd.read_excel(config.volc_file)
        A = A[A["nearestVnum"].isin(VOLCS.vnum.values)]

        # Flag strokes at volcanoes where alert is desired
        VOLCS = VOLCS[VOLCS["Lightning"] == "Y"]
        A.loc[
            A.index[A["nearestVnum"].isin(VOLCS.vnum.values)].tolist(), "send_alert"
        ] = True

        A_recent, A_new = get_new_strokes(A, T0, config)
        volcanoes = A_new.volcanoName.unique()

    else:
        volcanoes = []
        A_recent = make_blank_df()

    if len(volcanoes) == 0:
        logger.info("****** No lightning detected ******")
        state = "OK"
        state_message = f"{t_string} (UTC) No new strokes detected"
        A_recent.to_csv(config.outfile, index=False)

    else:
        logger.info(f"Lightning detected at {len(volcanoes):.0f} volcanoe(s)")
        for v in volcanoes:
            if not v:
                logger.warning("Null volcano. Skipping...")
                continue

            logger.info(f"--- Processing detects at {v} volcano ---")
            V_new = A_new[A_new["volcanoName"] == v]

            if not V_new.iloc[0].send_alert:
                logger.info(f"Ignoring {v} Lightning")
                state = "WARNING"
                state_message = f"{t_string} (UTC) New strokes at {v} (ignored)"
                ignored_volcanoes.append(v)
                continue

            V_recent = get_distances(
                A_recent, V_new.iloc[0].volcanoLatitude, V_new.iloc[0].volcanoLongitude
            )
            V_recent = V_recent[V_recent["latest_distance"] < config.dist2]
            
            
            # check if changing volcanoes means no events < dist2 ???????
            # ????????
            if len(V_recent) == 0:
                continue

            V_recent = sort_by_time(V_recent)
            n_ring1, n_ring2 = inner_outer(V_recent.latest_distance, config)

            if len(A_new) == 0:
                logger.info("********** OLD DETECTION **********")
                state = "WARNING"
                state_message = get_state_message(state, t_string, V_recent.iloc[0].volcanoName, n_ring1, n_ring2, config, len(A_new))
                A_recent.to_csv(config.outfile, index=False)
            else:
                logger.info("********** NEW DETECTION **********")
                A_recent.to_csv(config.outfile, index=False)
                config.dist1 = 1e8
                if V_recent.iloc[-1].latest_distance > config.dist1:
                    logger.info("...distal detection 1st.")
                    state = "WARNING"
                    state_message = get_state_message(state, t_string, V_recent.iloc[0].volcanoName, n_ring1, n_ring2, config, len(A_new))
                else:
                    logger.info('********** PROXIMAL DETECTION 1st **********')
                    state = "CRITICAL"
                    state_message = get_state_message(state, t_string, V_recent.iloc[0].volcanoName, n_ring1, n_ring2, config, len(A_new))

                    ### Send Email Notification ####
                    logger.info("Crafting message...")
                    subject, message = create_message(V_recent, V_new, config)
                    try:
                        filename = plot_fig(V_recent, config, T0)
                    except Exception as e:
                        logger.error("Error generating figure...")
                        logger.error(e)
                        logger.error(traceback.format_exc())
                        filename = None

                    ### Send message ###
                    try:
                        mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
                        message = f"{message}\n\n{mm_url}"
                    except Exception as e:
                        logger.error("problem posting to mattermost")
                        logger.error(e)
                        logger.error(traceback.format_exc())
                        
                    messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)
                    # delete the file you just sent
                    if filename:
                        os.remove(filename)

    logger.info("Ignored: {}".format(ignored_volcanoes))
    messaging.icinga(config, state, state_message, send=icinga_flag)


def make_blank_df():
    columns = [
        "dataSource",
        "lightningId",
        "lightningLatitude",
        "lightningLongitude",
        "lightningTimestamp",
        "nearestDistanceKm",
        "volcanoLatitude",
        "volcanoLongitude",
        "volcanoName",
        "nearestVnum",
        "datetime",
    ]

    df = pd.DataFrame([], columns=columns)

    for c in df.columns:
        if c in ["dataSource", "volcanoName", "datetime"]:
            continue
        df[c] = pd.to_numeric(df[c])

    return df


def get_new_strokes(A, T0, config):

    # clean up the dataframe, removing excess columns
    A_recent = A.drop(
        [
            "volcanoElevationM",
            # 'nearestVnum',
            "peakCurrent",
            "residual",
            "stationTotal",
            "usgsDelaySeconds",
            "usgsInsertDate",
            "usgsTimestamp",
            "flashType",
            "icHeight",
            "icMultiplicity",
            "isAvoInd",
            "lightningDate",
            "cgMultiplicity",
        ],
        axis=1,
    )

    # convert strings to numbers
    for c in A_recent.columns:
        if c in ["dataSource", "volcanoName", "datetime", "obsAbbr"]:
            continue
        A_recent[c] = pd.to_numeric(A_recent[c])

    # get old detections
    B = pd.read_csv(config.outfile)

    # convert linux time to datetime
    A_recent["datetime"] = pd.to_datetime(A_recent.lightningTimestamp, unit="s")
    B["datetime"] = pd.to_datetime(B.lightningTimestamp, unit="s")

    # remove detections > X time ago
    A_recent = A_recent[
        A_recent["datetime"] > (T0 - config.duration).strftime("%Y%m%d %H%M%S.%f")
    ]
    B = B[B["datetime"] > (T0 - config.duration).strftime("%Y%m%d %H%M%S.%f")]

    # Calculate distance from each stroke to the volcano
    # & deal with encoding issue in volcanoe name
    X = np.array([])
    for i, row in A_recent.iterrows():
        if row.volcanoName:
            # A_recent.loc[i,'volcanoName']=row.volcanoName.encode('utf-8')
            pass
        x = (
            gps2dist_azimuth(
                row.lightningLatitude,
                row.lightningLongitude,
                row.volcanoLatitude,
                row.volcanoLongitude,
            )[0]
            / 1000.0
        )
        X = np.append(X, x)
    A_recent["nearestDistanceKm"] = X

    # restric strokes to within the outer ring
    A_recent = A_recent[A_recent["nearestDistanceKm"] < config.dist2]

    # convert lightningId to integer
    A_recent["lightningId"] = pd.to_numeric(A_recent["lightningId"])

    # get dataframe containing strokes that haven't already been alerted on
    A_new = A_recent[~A_recent.lightningId.isin(B.lightningId)]

    return A_recent, A_new


def sort_by_time(df):

    # sort from most recent down to oldest
    df2 = df.copy()
    df2.sort_values("datetime", inplace=True, ascending=False)
    df2.reset_index()

    return df2


def get_distances(df, vlat, vlon):

    df2 = df.copy()

    # get distance in km for all strokes to volcano nearest to most recent stroke
    X  = np.array([gps2dist_azimuth(vlat, vlon, row.lightningLatitude, row.lightningLongitude)[0]/1000 for i,row in df.iterrows()])
    AZ = np.array([gps2dist_azimuth(vlat, vlon, row.lightningLatitude, row.lightningLongitude)[1] for i,row in df.iterrows()])

    df2["latest_distance"] = X
    df2["latest_azimuth"] = AZ

    return df2


def inner_outer(X, config):

    n_ring1 = len(X[X < config.dist1])
    Y = X[X > config.dist1]
    n_ring2 = len(Y[Y < config.dist2])

    return n_ring1, n_ring2


def get_state_message(state, t_string, v_name, n_ring1, n_ring2, config, N_new):
    match state:
        case "WARNING":
            if N_new == 0:
                state_message = f"{t_string} (UTC) {v_name} Lightning Detection!"
            else:
                state_message = f"{t_string} (UTC) {v_name} Distal Lightning Detection!"
        case "CRITICAL":
            state_message = f"{t_string} (UTC) {v_name} Lightning Detection!"
            state_message = f"{state_message} {N_new} new strokes!"

    state_message = f"{state_message} {n_ring1} strokes < 20 km (20 km < {n_ring2} < 100 km)"
    state_message = f"{state_message} in past {config.duration/60.0:.0f} minutes."

    return state_message


def get_direction(azimuth):
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    ix = int(np.round(azimuth / (360 / len(dirs))))

    return dirs[ix % len(dirs)]


def create_message(V_recent, V_new, config):
    # create the subject line
    v_last = V_recent.iloc[0]
    v_name = v_last.volcanoName
    subject = f"--- {v_name} Lightning ---"

    # create the test for the message you want to send
    if len(V_new) == 1:
        message = f"\n{len(V_new)} new stroke! ({len(V_recent)} total)"
    else:
        message = f"\n{len(V_new)} new strokes! ({len(V_recent)} total)"

    message = f"{message}\n\n-- Most recent --"
    t = utc(V_recent.iloc[0].datetime)
    message = f"{message}\n{messaging.format_timestring(t)}"

    dist = v_last.latest_distance
    direction = get_direction(v_last.latest_azimuth)
    message = f"{message}\n{dist:.0f} km {direction} of {v_name},"
    message = "{}\n\nData source: {}".format(
        message, ", ".join(V_new.dataSource.unique()).replace("EN", "Earth Networks")
    )

    return subject, message


def plot_fig(A_recent, config, T0):
    
    fig, ax = plt.subplots(figsize=(3.4, 3.15))

    lat0 = A_recent.iloc[0].volcanoLatitude
    lon0 = A_recent.iloc[0].volcanoLongitude
    v_name = A_recent.iloc[0].volcanoName
    t_recent = A_recent.iloc[0].datetime.strftime('%Y-%m-%d %H:%M:%S')

    X_DIST = getattr(config, "map_xdist", 100)
    Y_DIST = getattr(config, "map_ydist", 100)
    
    ax, extent = plotting.make_map(ax, lat0, lon0, basemap="HIGHRES", xdist=X_DIST, ydist=Y_DIST)
    ax.set_title(f"--- {v_name} Lightning ---\n{t_recent} UTC", fontsize=8)
    plotting.map_ticks(ax, extent, grid_kwargs="default")
    plotting.add_volcanoes_to_map(ax, extent, config, linewidths=0.1)
    plotting.add_scale_bar(ax, 15, txt_yoffset=0.01)

    G = A_recent.copy()
    G.sort_values('datetime', inplace=True, ascending=True)
    map_hdl = ax.scatter(G.lightningLongitude.values,
                            G.lightningLatitude.values,
                            s=14,
                            c=date2num(G.datetime),
                            cmap='plasma',
                            vmin=date2num((T0-config.duration).datetime), 
                            vmax=date2num(T0.datetime),
                            edgecolors='k',
                            linewidth=0.2,
                            transform=ccrs.Geodetic(),
                            zorder=1e5)

    if len(G) > 1:
        cbaxes = inset_axes(ax, height="70%", width="4%", loc=6, borderpad=-1) 
        cbar = plt.colorbar(map_hdl, cax=cbaxes, orientation='vertical')
        cbaxes.yaxis.set_ticks_position('left')
        cbar.set_ticks([date2num((T0-config.duration).datetime), date2num(T0.datetime)])
        cbar.set_ticklabels(['{:.0f}\nmin\nago'.format(config.duration/60), 'Now'])
        cbar.ax.tick_params(labelsize=6)

    ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
    ax_inset, inset_extent = plotting.make_map(ax_inset, lat0, lon0,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_volcanoes_to_map(ax_inset, inset_extent, config, s1=7, s2=4, linewidths=0.1)
    plotting.add_inset_polygon(ax_inset, extent, ec="red", fc="none", linewidth=0.3)

    jpg_file = plotting.save_file(fig, config, dpi=300)

    return jpg_file