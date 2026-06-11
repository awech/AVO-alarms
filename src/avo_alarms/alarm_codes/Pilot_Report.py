import os
import re
import traceback
from textwrap import wrap

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
from obspy import UTCDateTime as utc

from avo_alarms.utils import messaging, plotting, processing, downloading, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime("%Y-%m-%d %H:%M")

    state, archive = downloading.download_pilot_reports(T0, config)
    state_message = f"{T0_str} (UTC) No new pilot reports"
    if archive is None:
        if state == "WARNING":
            state_message = f"{T0_str} (UTC) PIREP API error. Cannot retrieve shape file"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    pirep_df = processing.pirep_archive_to_dataframe(T0, config, archive)
    pirep_df = processing.find_nearest_volcano(pirep_df, lon_col="lon", lat_col="lat")
    pirep_df = pirep_df[pirep_df["v_distance"] < config.max_distance]

    ## BUG 'PROD_ID' is not entirely unique. See events at 2026-05-21 17:08 and 17:09
    N_new, N_old = alarming.check_new_event_ids(pirep_df["PROD_ID"], test=test_flag)
    logger.info(f"Found {N_new} new and {N_old} old PIREPS")

    if force_flag:
        pirep_df = pirep_df[:1]
    else:
        pirep_df = processing.check_volcano_mention(pirep_df)
        pirep_df = pirep_df[pirep_df["trigger"]]

    for i, row in pirep_df.iterrows():

        if alarming.already_processed(config, row.PROD_ID, test=test_flag):
            logger.info("PIREPS found have already been processed")
            state == "OK"
            state_message = f"{T0_str} (UTC) No new pilot reports"
            continue

        state = "WARNING"
        try:
            filename = plot_fig(row, config, test=test_flag)
        except Exception as e:
            logger.error('Error generating figure...')
            logger.error(e)
            logger.error(traceback.format_exc())
            filename = []

        ### Craft message text ####
        subject, message = create_message(row, config)
        state_message = message

        try:
            mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
            message = f"{message}\n\n{mm_url}"
        except Exception as e:
            logger.error("Problem posting to mattermost")
            logger.error(e)

        ### Send message to duty person ###
        if row.URGENT == "T" or force_flag:
            state = "CRITICAL"
            messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

        alarming.record_send(
            config,
            T0,
            volcano=row.v_name,
            event_id=row.PROD_ID,
            test=test_flag,
        )
        # delete the file you just sent
        if filename:
            os.remove(filename)

    # if not force_flag:
    #     processing.write_to_csv(pirep_df, config, outfile_columns)
    messaging.icinga(config, state, state_message, send=icinga_flag)

    return


def get_height_text(FL):
    try:
        height_text = f"Flight level: {FL:,.0f} feet asl"
    except Exception:
        logger.warning('Could not parse flight level from report')
        height_text = "Flight level: UNKNOWN"
    return height_text


def get_pilot_remark(report):

    pattern = re.compile(r'^(?:\s)?RM(.*)$')
    fields = report.split("/")

    pilot_remark = ""
    for f in fields:
        m = pattern.match(f)
        if m:
            pilot_remark = m.group(1)
            pilot_remark = pilot_remark.strip()
            pilot_remark = pilot_remark.capitalize()
            logger.info(f"Pilot remark: {pilot_remark}")

    if not pilot_remark:
        pilot_remark = "NA"
        logger.warning("Unable to extract pilot remarks")

    return pilot_remark


def create_message(pirep_row, config):

    message = messaging.format_timestring(utc(pirep_row.time))
    message += f"\n{get_height_text(pirep_row.FL)}\nPilot Remark: {get_pilot_remark(pirep_row.REPORT)}"
    message += f"\nLatitude: {pirep_row.lat:.3f}\nLongitude: {pirep_row.lon:.3f}\n"

    volcs = load_volcano_list()
    volcs = processing.volcano_distance(pirep_row.lon, pirep_row.lat, volcs)

    v_text = ""
    for j, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Name} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}Nearest volcanoes: {v_text[:-2]}\n"
    message = f"{message}\n--Original Report--\n{pirep_row.REPORT}"
    logger.info(message)

    if pirep_row.URGENT == "T":
        subject = f"URGENT! Activity possible at: {v_text[:-2]}"
    else:
        subject = f"Activity possible at: {v_text[:-2]}"

    return subject, message


def plot_fig(pirep_row, config, test=False):

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
    ax_inset, inset_extent = plotting.make_map(
        ax_inset,
        pirep_row.lat,
        pirep_row.lon,
        xdist=800,
        ydist=600,
        basemap="land",
        projection="orthographic",
    )

    plotting.add_inset_polygon(ax_inset, extent)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=300)

    return jpg_file
