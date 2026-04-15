import os
import traceback
import warnings
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from obspy.geodetics.base import gps2dist_azimuth

from ..utils import messaging, plotting, processing
from ..utils.setup_utils import get_logger

logger = get_logger(__name__)

plt.style.use(Path("utils") / "alarms.mplstyle")
warnings.filterwarnings("ignore")

client = processing.IRIS_client()

def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    # Download the event data
    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    logger.info(f"{T0_str}\nDownloading events...")
    T2 = T0
    T1 = T2 - config.DURATION

    URL = (
        f"{os.environ['FDSN_URL']}"
        f"starttime={T1.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&endtime={T2.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&minmagnitude={config.MAGMIN}"
        f"&maxdepth={config.MAXDEP}"
        f"&format=csv"
    )
    catalog_df = processing.download_hypocenters_csv(URL)

    if catalog_df is None: # Error pulling events
        state = "WARNING"
        state_message = f"{T0_str} (UTC) FDSN connection error"
        logger.warning(state_message)
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    if len(catalog_df) == 0: # No events
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        logger.info(state_message)
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Compare new event distance with volcanoes
    catalog_df = update_catalog_dataframe(catalog_df, config)
    catalog_df = catalog_df[catalog_df["V_DIST"] < config.DISTANCE]

    # New events, but not close enough to volcanoes
    if len(catalog_df) == 0:
        logger.warning("Earthquakes detected, but not near any volcanoes")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Read in old events. Write all recent events. Filter to new events
    OLD_EVENTS = pd.read_csv(config.outfile) 
    catalog_df[["ID"]].to_csv(config.outfile, index=False)
    new_events_df = catalog_df[~catalog_df["ID"].isin(OLD_EVENTS.ID)]
    new_events_df = new_events_df.sort_values("Time")

    # No new events to process
    if len(new_events_df) == 0:
        logger.warning("Earthquakes detected, but already processed in previous run")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Old event detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    logger.info(f"{len(new_events_df)} new events found. Looping through events...")
    for i, row in new_events_df.iterrows():
        logger.info(f"Processing event {row.ID}")
        evt_url = "{}eventid={}".format(os.environ['FDSN_URL'], row.ID)
        logger.info(f"Downloading\n{evt_url}")
        subject, message, attachment, eq = process_eq(evt_url, config)

        logger.info("Sending message...")
        messaging.send_alert(config.alarm_name, subject, message, attachment=attachment, test=test_flag)
        logger.info("Posting to mattermost...")
        messaging.post_mattermost(config, subject, message, attachment=attachment, send=mm_flag, test=test_flag)

        # Post to dedicated response channels for volcnoes listed in config file
        # if "mm_response_channels" in dir(config):
        #     if volcs.iloc[0].Volcano in config.mm_response_channels.keys():
        #         config.mattermost_channel_id = config.mm_response_channels[volcs.iloc[0].Volcano]
        #         messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)

        # delete the file you just sent
        if attachment:
            os.remove(attachment)

        state = "CRITICAL"
        eq_str = eq.preferred_origin().time.strftime("%Y-%m-%d %H:%M:%S")
        state_message = f"{eq_str} (UTC) {subject}"

    messaging.icinga(config, state, state_message, send=icinga_flag)


def process_event(evt_url, config):

    cat = processing.download_hypocenter_xml(evt_url)
    try:
        cat = processing.addPhaseHint(cat)
    except Exception as e:
        logger.warning('Could not add phase type...')
        logger.error(e)

    # Find nearby volcanoes
    eq = cat[0]
    volcs = pd.read_excel(config.volc_file)
    volcs = processing.volcano_distance(eq.preferred_origin().longitude, eq.preferred_origin().latitude, volcs)
    volcs = volcs.sort_values('distance')

    try:
        filename = plot_event(eq, volcs, config)
        fig_dir = Path(os.environ["TMP_FIGURE_DIR"])
        eq_time = eq.preferred_origin().time.strftime("%Y%m%dT%H%M%S")
        eq_mag = eq.preferred_magnitude().mag
        eq_id = "".join(eq.resource_id.id.split("/")[-2:]).lower()
        new_filename = fig_dir / f"{eq_time}_M{eq_mag:.1f}_{eq_id}{filename.suffix}"
        os.rename(filename, new_filename)
        filename = new_filename
    except Exception as e:
        filename = []
        logger.error("Problem making figure. Continue anyway")
        logger.error(e)
        logger.error(traceback.format_exc())

    subject, message = create_message(eq, volcs)

    return subject, message, filename, eq


def update_catalog_dataframe(cat_df, config):

    VOLCS = pd.read_excel(config.volc_file)
    V_DIST = []

    for _, eq in cat_df.iterrows():
        volcs = processing.volcano_distance(eq.longitude, eq.latitude, VOLCS)
        volcs = volcs.sort_values("distance")
        V_DIST.append(volcs.iloc[0].distance)

    cat_df.columns = cat_df.columns.str.capitalize()
    cat_df.rename(columns={"Mag": "Magnitude",
                            "Id": "ID"},
                inplace=True)
    cat_df["V_DIST"] = V_DIST
    cat_df['Time'] = pd.to_datetime(cat_df['Time'])

    return cat_df


def create_message(eq, volcs):
    origin = eq.preferred_origin()
    t = pd.Timestamp(origin.time.datetime, tz="UTC")
    t_local = t.tz_convert(os.environ["TIMEZONE"])
    Local_time_text = f"{t_local.strftime("%Y-%m-%d %H:%M:%S")} {t_local.tzname()}"

    message = f"{t.strftime('%Y-%m-%d %H:%M:%S')} UTC\n{Local_time_text}"
    message = f"{message}\n\n**Magnitude:** {eq.preferred_magnitude().mag:.1f}"
    message = f"{message}\n**Latitude:** {origin.latitude:.3f}\n**Longitude:** {origin.longitude:.3f}"
    message = f"{message}\n**Depth:** {origin.depth / 1000:.1f} km"
    message = f"{message}\n**Event ID:** {''.join(eq.resource_id.id.split('/')[-2:]).lower()}"

    volcs = volcs.sort_values("distance")
    v_text = ""
    for _, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Volcano} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}\n**Nearest volcanoes:** {v_text[:-2]}"

    try:
        message = f"{message}\n\n***--- {origin.evaluation_mode.replace('manual', 'reviewed').upper()} Location ---***"
        message = f"{message}\nUsing {origin.quality.used_phase_count:g} phases from {origin.quality.used_station_count:g} stations"
        message = f"{message}\n**Azimuthal Gap:** {origin.quality.azimuthal_gap:g} degrees"
        message = f"{message}\n**Standard Error:** {origin.quality.standard_error:g} s"
        message = f"{message}\n**Vertical/Horizontal Error:** {origin.depth_errors['uncertainty'] / 1000:.1f} km / {origin.origin_uncertainty.horizontal_uncertainty / 1000:.1f} km"
    except:
        pass

    subject = f"M{eq.preferred_magnitude().mag:.1f} earthquake at {volcs.iloc[0].Volcano}"

    return subject, message


def get_channels(eq):

    NS = []
    NSLC = []
    SCNL = []
    LATS = []
    LONS = []
    DIST = []
    P = []
    S = []
    for p in eq.picks:
        wid = p.waveform_id
        net, sta, loc, chan = wid.id.split(".")
        ns = ".".join([net, sta])
        if ns not in NS:
            logger.info(f"Getting lat/lon info for {wid.id}")
            inventory = client.get_stations(
                network=net, station=sta, location=loc, channel=chan
            )
            # NSLC.append(wid.id.replace('..','.--.'))
            NS.append(ns)
            NSLC.append(wid.id)
            SCNL.append(".".join([sta, chan, net, loc]))
            LATS.append(inventory[0][0].latitude)
            LONS.append(inventory[0][0].longitude)
    for i, nslc in enumerate(NSLC):
        dist = (
            gps2dist_azimuth(
                eq.preferred_origin().latitude,
                eq.preferred_origin().longitude,
                LATS[i],
                LONS[i],
            )[0]
            / 1000.0
        )
        DIST.append(dist)

    STAS = pd.DataFrame(
        {
            "NS": NS,
            "NSLC": NSLC,
            "SCNL": SCNL,
            "Latitude": LATS,
            "Longitude": LONS,
            "Distance": DIST,
        }
    )

    STAS["P"] = np.nan
    STAS["S"] = np.nan
    for p in eq.picks:
        ns = ".".join(p.waveform_id.id.split(".")[:2])
        STAS.loc[STAS.NS == ns, p.phase_hint] = p.time

    STAS = STAS.sort_values("Distance")

    return STAS


def plot_event(eq, volcs, config, n_stations=8):

    ################### Download data ###################
    channels = get_channels(eq)
    plot_chans = channels[:n_stations]
    st = processing.grab_data(list(plot_chans.SCNL.values), 
                        eq.preferred_origin().time-20, 
                        eq.preferred_origin().time+50)

    logger.info("Plotting traces...")
    axes_list, h_ratios = plotting.get_axes_and_ratios(st)
    fig, ax = plt.subplot_mosaic(
        axes_list,
        figsize=(4, 9),
        height_ratios=h_ratios,
    )

    plotting.plot_station_traces(ax, st, plot_chans)

    vlat = volcs.iloc[0]["Latitude"]
    vlon = volcs.iloc[0]["Longitude"]
    ax["map"], extent = plotting.make_map(
        ax["map"],
        vlat,
        vlon,
        basemap="hillshade",
        xdist=getattr(config, "map_distance", 50),
        ydist=getattr(config, "map_distance", 50)
    )

    plotting.map_ticks(ax["map"], extent, grid_kwargs="default", y_rotate=90)
    ax["map"].tick_params(length=0)

    plotting.add_volcanoes_to_map(ax["map"], extent, config)
    ax["map"].plot(channels.Longitude, channels.Latitude, 's', markerfacecolor='orange', markersize=5, markeredgecolor='k', markeredgewidth=0.4, transform=ccrs.PlateCarree())
    ax["map"].plot(eq.preferred_origin().longitude, eq.preferred_origin().latitude, 'o', markerfacecolor='firebrick', markersize=8, markeredgecolor='k', markeredgewidth=0.7, transform=ccrs.PlateCarree())
    for i, row in channels.iterrows():
        t = ax["map"].annotate(row.NS.split('.')[-1], (row.Longitude, row.Latitude), xytext=(10,10), textcoords="offset pixels", fontsize=6, transform=ccrs.Geodetic())
        t.clipbox = ax["map"].bbox

    plotting.add_scale_bar(ax["map"], 10, txt_yoffset=0.01)
    ax["map"].set_title('{}\nM{:.1f}, {:.1f} km from {}\nDepth: {:.1f} km'.format(eq.preferred_origin().time.strftime('%Y-%m-%d %H:%M:%S'),
                                                               eq.preferred_magnitude().mag,
                                                               volcs.iloc[0].distance,
                                                               volcs.iloc[0].Volcano,
                                                               eq.preferred_origin().depth/1000,
                                                               ),
                        fontsize=8)

    ax_inset = fig.add_axes([0.66, 0.80, 0.12, 0.12])
    ax_inset, _ = plotting.make_map(
        ax_inset,
        vlat,
        vlon,
        xdist=150,
        ydist=150,
        basemap="land",
        projection="orthographic",
    )

    plotting.add_inset_polygon(
        ax_inset, extent, facecolor="none", edgecolor="red", linewidth=0.35
    )

    logger.info('Saving figure...')
    jpg_file = plotting.save_file(fig, config, dpi=200)
    plt.close(fig)

    return jpg_file
