import os
import re
import traceback
import warnings

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from avo_alarms.utils import messaging, plotting, processing, downloading
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)
warnings.filterwarnings("ignore")


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    max_distance = getattr(config, "max_distance", 25)
    outfile_columns = ["time", "NOAA_id", "vv_id"]
    
    logger.info("Reading in alerts from volcview api .json file")
    cimss_df = downloading.download_cimss_vv_api()
    if cimss_df is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Error getting data from Volcview-API"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    cimss_df = processing.format_cimss_dataframe(cimss_df, config, T0)
    cimss_df = processing.find_nearest_volcano(cimss_df, config, lon_col="lon_rc", lat_col="lat_rc")
    cimss_df = cimss_df[cimss_df["v_distance"] < max_distance]
    cimss_df = processing.check_ignore_volcano(cimss_df)
    cimss_df = cimss_df[cimss_df["keep"]]
    
    new_alerts_df, cimss_df = processing.compare_to_old_events(
        cimss_df, config.outfile, outfile_columns, unique_id_col="NOAA_id"
    )

    if len(new_alerts_df) == 0:
        if len(cimss_df) > 0:
            logger.info("NOAA CIMSS alerts found have already been processed")
        processing.write_to_csv(cimss_df, config, outfile_columns)
        state = "OK"
        state_message = f"{T0_str} (UTC) No new recent NOAA CIMSS alerts"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    default_mm_id = config.mattermost_channel_id

    logger.info("Looping through alerts...")
    for _, alert in new_alerts_df.iterrows():

        logger.info(f"--- New Alert! ---\n{alert}")
        logger.info("Scraping images and info from NOAA CIMSS page...")

        alert_html_soup = downloading.scrape_cimss_alert(alert)
        if not alert_html_soup:
            logger.error("Error reading NOAA CIMSS page")
            state = "WARNING"
            state_message = f"{T0_str} (UTC) NOAA/CIMSS webpage error"
            continue
        
        alert, output_text = process_alert_soup(alert_html_soup, alert, config)
        if not output_text:
            logger.error("Error processing NOAA CIMSS page")
            state = "WARNING"
            state_message = f"{T0_str} (UTC) NOAA/CIMSS webpage error"
            continue

        try:
            logger.info("Done. Attempting to generate figure")
            filename = plot_fig(alert, config, test=test_flag)
            logger.info("Figure generated successfully")
        except Exception as e:
            filename = []
            logger.error("Problem making figure. Continue anyway")
            logger.error(e)
            logger.error(traceback.format_exc())
            pass

        logger.info("Crafting message...")
        volcs = load_volcano_list()
        volcs = processing.volcano_distance(alert.lon_rc, alert.lat_rc, volcs)
        subject, message = create_message(alert, volcs, output_text)

        logger.info("Posting to mattermost...")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
        # send to other mm channels based on alert type and volcano status
        messaging.cimss_mm_channels(alert, config, subject, message, filename, test_flag, mm_flag)
        # change mm channel id back to default
        config.mattermost_channel_id = default_mm_id

        state = "CRITICAL"
        state_message = f"{T0_str} (UTC) {subject}"

        if filename:
            os.remove(filename)

        processing.write_to_csv(cimss_df, config, outfile_columns)

    messaging.icinga(config, state, state_message, send=icinga_flag)


def create_message(alert, volcs, output_text):

    t = utc(alert.object_date_time)
    instrument = output_text["instrument"]
    height_txt = output_text["height_txt"]
    status_txt = output_text["status_txt"]
    type_txt = output_text["type_txt"]
    message = messaging.format_timestring(t)


    message += f"\n**Primary Instrument:** {instrument}"
    if height_txt:
        height_txt = height_txt.replace("Max", "**Max").replace("]:", "]:**")
        message += f"\n{height_txt}"
    if status_txt:
        status_txt = status_txt.replace("Alert", "**Alert").replace(":", ":**")
        message += f"\n{status_txt}"
    if type_txt:
        type_txt = type_txt.replace("Type of Volcanic Event:", "**Event type:**")
        message += f"\n{type_txt}"
    message += f"\n**Latitude:** {alert.lat_rc:.3f}\n**Longitude:** {alert.lon_rc:.3f}\n"

    v_text = ""
    for i, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Volcano} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")

    message += f"**Method:** {alert.method}\n"
    message += f"**Nearest volcanoes:** {v_text[:-2]}\n\n"
    message += f"**More info:** {alert.alert_url.replace('report/' + str(alert.NOAA_id), 'individual/' + str(alert.aid))}\n"

    subject_text = alert.alert_header.title().replace(" Found", "")
    subject_text = subject_text.replace(" Detected", "")
    subject = f"{volcs.iloc[0].Volcano}: {subject_text}"

    return subject, message


def process_alert_soup(soup, alert, config):

    output = {}
    try:
        output["instrument"] = get_instrument(soup)
        sections = soup.select("div[class*=alert_box]")
    except Exception as e:
        logger.error("Error processing NOAA CIMSS alert page")
        logger.error(e)
        return alert, None

    for soupy in sections:
        t = get_timestamp(soupy)
        lat_web, lon_web = get_latitude(soupy)
        if t:
            if (
                utc(alert.object_date_time) - utc(t)
            ) == 0 & (
                gps2dist_azimuth(
                    lat_web, lon_web, alert.lat_rc, alert.lon_rc
                )[0]
                / 1000
                == 0
            ):

                output["height_txt"] = get_height_txt(soupy)
                output["status_txt"] = get_alert_status_txt(soupy)
                output["type_txt"] = get_type_txt(soupy)

                downloading.get_cimss_image(soupy, alert, config)

                tmp_text = soupy.select("a[href*=individual]")
                aid = np.unique(
                    [
                        x["href"].split("#")[0].split("/")[-1]
                        for x in tmp_text
                    ]
                )
                alert["aid"] = aid

                break
    return alert, output


def get_instrument(soup):

    tbl = soup.find("div", {"class": "alert_box alert_report_summary"})
    rows = tbl.find_all("tr")
    row = [tr for tr in rows if "Primary" in str(tr)]
    instrument = row[0].find("td").text

    return instrument


def get_height_txt(soup):

    height_txt = soup.find(text=re.compile("Maximum Height [AMSL]"))
    if height_txt:
        height_txt += ":  " + height_txt.find_all_next("td")[0].text

    return height_txt


def get_alert_status_txt(soup):

    status_txt = soup.find(text=re.compile("Alert Status"))
    if status_txt:
        status_txt += ":  " + status_txt.find_all_next("td")[0].text

    return status_txt


def get_type_txt(soup):

    type_txt = soup.find(text=re.compile("Type of Volcanic Event"))
    if type_txt:
        type_txt += ":  " + type_txt.find_all_next("td")[0].text

    return type_txt


def get_timestamp(soup):

    time_txt = soup.find(text=re.compile("Date/Time"))
    if time_txt:
        time_txt = time_txt.find_all_next("td")[0].text.split("UTC")[0]

    return time_txt


def get_latitude(soup):

    lat_txt = soup.find(text=re.compile("Radiative Center"))
    lat = None
    lon = None
    if lat_txt:
        lat_txt = lat_txt.find_all_next("td")[0]
        lat, lon = re.findall(r"[-+]?(?:\d*\.*\d+)", lat_txt.text)
        lat = float(lat)
        lon = float(lon)

    return lat, lon


def plot_fig(alert, config, test=False):

    fig, ax = plt.subplot_mosaic(
        [["img1"], ["img2"], ["map"]],
        figsize=(3, 6.6),
        height_ratios=[1.1, 1.1, 1]
    )

    title_str = "{} UTC\n{}\nMethod: {}".format(
        str(alert.object_date_time), alert.alert_header.capitalize(), alert.method
    )
    ax["img1"].set_title(title_str, fontsize=8)
    
    # read in images downloaded from NOAA/CIMSS webpage
    tmp_file1 = config.img_file.replace(".png", "1.png")
    tmp_file2 = config.img_file.replace(".png", "2.png")
    img1 = mpimg.imread(tmp_file1)
    img2 = mpimg.imread(tmp_file2)

    ax["img1"].imshow(img1)
    ax["img1"].set_xticks([])
    ax["img1"].set_yticks([])

    ax["img2"].imshow(img2)
    ax["img2"].set_xticks([])
    ax["img2"].set_yticks([])


    X_DIST = getattr(config, "map_xdist", 150)
    Y_DIST = getattr(config, "map_ydist", 150)
    ax["map"], extent = plotting.make_map(
        ax["map"],
        alert.lat_rc,
        alert.lon_rc,
        basemap="HIGHRES",
        xdist=X_DIST,
        ydist=Y_DIST,
    )

    plotting.map_ticks(ax["map"], extent, grid_kwargs="default")
    plotting.add_volcanoes_to_map(ax["map"], extent, config, linewidths=0.1)
    plotting.add_scale_bar(ax["map"], 25, txt_yoffset=0.02)

    # draw rectangle on inset map
    ax_inset = fig.add_axes([0.66, 0.25, 0.15, 0.15])
    ax_inset, inset_extent = plotting.make_map(ax_inset, alert.lat_rc, alert.lon_rc,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_inset_polygon(ax_inset, extent)
    fig.subplots_adjust(hspace=0.1)
    jpg_file = plotting.save_file(fig, config, test=test, dpi=500)

    # remove images downloaded from NOAA/CIMSS webpage
    os.remove(tmp_file1)
    os.remove(tmp_file2)

    return jpg_file
