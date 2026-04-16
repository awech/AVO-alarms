import os
import traceback
import warnings
from pathlib import Path

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import pandas as pd

from avo_alarms.utils import messaging, plotting, processing, downloading
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)

warnings.filterwarnings("ignore")


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    T2 = T0
    T1 = T2 - config.DURATION
    config.outfile = Path(config.outfile)
    outfile_columns = ["time", "id"]

    URL = (
        f"{os.getenv('FDSN_URL')}"
        f"starttime={T1.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&endtime={T2.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&minmagnitude={config.MAGMIN}"
        f"&maxdepth={config.MAXDEP}"
        f"&format=csv"
    )
    logger.info(f"{T0_str}\nDownloading events...")
    catalog_df = downloading.download_hypocenters_csv(URL)
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
    catalog_df = processing.find_nearest_volcano(catalog_df, config)
    catalog_df = catalog_df[catalog_df["v_distance"] < config.DISTANCE]

    # New events, but not close enough to volcanoes
    if len(catalog_df) == 0:
        logger.warning("Earthquakes detected, but not near any volcanoes")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Read in old events. Filter to new events. Write out old and new events.
    new_events_df, catalog_df = processing.compare_to_old_events(
        catalog_df, config.outfile, outfile_columns, unique_id_col="id"
    )

    # No new events to process
    if len(new_events_df) == 0:
        processing.write_to_csv(catalog_df, config, outfile_columns)
        logger.warning("Earthquakes detected, but already processed in previous run")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Old event detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    logger.info(f"{len(new_events_df)} new events found. Looping through events...")
    for i, row in new_events_df.iterrows():
        logger.info(f"Processing event {row.id}")
        evt_url = f"{os.getenv('FDSN_URL')}eventid={row.id}"
        subject, message, attachment, eq, volcs = process_event(evt_url, config, test=test_flag)

        logger.info("Sending message...")
        messaging.send_alert(
            config.alarm_name, subject, message, attachment=attachment, test=test_flag
        )
        logger.info("Posting to mattermost...")
        messaging.post_mattermost(
            config,
            subject,
            message,
            attachment=attachment,
            send=mm_flag,
            test=test_flag,
            volcano=volcs.iloc[0].Volcano,
        )

        # delete the file you just sent
        if attachment:
            os.remove(attachment)

        state = "CRITICAL"
        eq_str = eq.preferred_origin().time.strftime("%Y-%m-%d %H:%M:%S")
        state_message = f"{eq_str} (UTC) {subject}"

    processing.write_to_csv(catalog_df, config, outfile_columns)
    messaging.icinga(config, state, state_message, send=icinga_flag)


def process_event(evt_url, config, test=False):

    cat = downloading.download_hypocenter_xml(evt_url)
    try:
        cat = processing.addPhaseHint(cat)
    except Exception as e:
        logger.warning('Could not add phase type...')
        logger.error(e)

    # Find nearby volcanoes
    eq = cat[0]
    origin = eq.preferred_origin()
    volcs = pd.read_excel(config.volc_file)
    volcs = processing.volcano_distance(origin.longitude, origin.latitude, volcs)

    try:
        filename = plot_event(eq, volcs, config, test=test)
        fig_dir = Path(os.getenv("TMP_FIGURE_DIR"))
        eq_time = origin.time.strftime("%Y%m%dT%H%M%S")
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

    return subject, message, filename, eq, volcs


def create_message(eq, volcs):
    origin = eq.preferred_origin()
    t = pd.Timestamp(origin.time.datetime, tz="UTC")
    t_local = t.tz_convert(os.getenv("TIMEZONE"))
    Local_time_text = f"{t_local.strftime('%Y-%m-%d %H:%M:%S')} {t_local.tzname()}"

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
    except Exception as e:
        logger.warning("Problem adding location quality info to message. Continue anyway.")
        logger.warning(e)
        logger.warning(traceback.format_exc())
        pass

    subject = f"M{eq.preferred_magnitude().mag:.1f} earthquake at {volcs.iloc[0].Volcano}"

    return subject, message


def plot_event(eq, volcs, config, n_stations=8, test=False):

    ################### Download data ###################
    channels = processing.eq_picks_to_dataframe(eq)
    plot_chans = channels[:n_stations]
    origin = eq.preferred_origin()
    st = downloading.download_waveforms(
        list(plot_chans.SCNL.values), origin.time - 20, origin.time + 50
    )

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
    ax["map"].plot(channels.Longitude, channels.Latitude, 's', c='orange', ms=4, mec='k', mew=0.4, transform=ccrs.PlateCarree())
    ax["map"].plot(origin.longitude, origin.latitude, 'o', c='firebrick', ms=6, mec='k', mew=0.7, transform=ccrs.PlateCarree())
    for i, row in channels.iterrows():
        t = ax["map"].annotate(row.NS.split('.')[-1], (row.Longitude, row.Latitude), xytext=(10,10), textcoords="offset pixels", fontsize=6, transform=ccrs.Geodetic())
        t.clipbox = ax["map"].bbox

    plotting.add_scale_bar(ax["map"], 10, txt_yoffset=0.01)
    ax["map"].set_title('{}\nM{:.1f}, {:.1f} km from {}\nDepth: {:.1f} km'.format(origin.time.strftime('%Y-%m-%d %H:%M:%S'),
                                                               eq.preferred_magnitude().mag,
                                                               volcs.iloc[0].distance,
                                                               volcs.iloc[0].Volcano,
                                                               origin.depth/1000,
                                                               ),
                        fontsize=8)

    ax_inset = fig.add_axes([0.66, 0.80, 0.12, 0.12])
    ax_inset, _ = plotting.make_map(
        ax_inset,
        vlat,
        vlon,
        xdist=getattr(config, "inset_map_distance", 150),
        ydist=getattr(config, "inset_map_distance", 150),
        basemap="land",
        projection="orthographic",
    )

    plotting.add_inset_polygon(ax_inset, extent)

    logger.info('Saving figure...')
    jpg_file = plotting.save_file(fig, config, test=test)

    return jpg_file
