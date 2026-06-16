import os
import traceback
import warnings

from avo_alarms.utils import messaging, processing, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import (
    download_cimss_vv_api,
    scrape_cimss_alert,
    get_cimss_image,
    format_cimss_dataframe,
    check_ignore_volcano,
    process_alert_soup,
)
from .message import create_message, cimss_mm_channels
from .figure import plot_fig

logger = get_logger(__name__)
warnings.filterwarnings("ignore")


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    max_distance = getattr(config, "max_distance", 25)
    
    logger.info("Reading in alerts from volcview api .json file")
    cimss_df = download_cimss_vv_api()
    if cimss_df is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Error getting data from Volcview-API"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    cimss_df = format_cimss_dataframe(cimss_df, config, T0)
    cimss_df = processing.find_nearest_volcano(cimss_df, lon_col="lon_rc", lat_col="lat_rc")
    cimss_df = cimss_df[cimss_df["v_distance"] < max_distance]
    cimss_df = check_ignore_volcano(cimss_df)
    cimss_df = cimss_df[cimss_df["keep"]]

    N_new, N_old = alarming.check_new_event_ids(cimss_df["NOAA_id"], test=test_flag)
    logger.info(f"Found {N_new} new and {N_old} old alerts")
    state = "OK"
    state_message = f"{T0_str} (UTC) No new recent NOAA CIMSS alerts"

    if force_flag:
        logger.warning(
            "Attempting to force trigger by grabbing most recent (even if already processed)"
        )
        cimss_df = cimss_df[:1]


    default_mm_id = config.mattermost_channel_id

    logger.info("Looping through alerts...")
    for _, alert in cimss_df.iterrows():

        if alarming.already_processed(config, alert.NOAA_id, test=test_flag):
            logger.info("NOAA CIMSS found have already been processed")
            state = "OK"
            state_message = f"{T0_str} (UTC) No new recent NOAA CIMSS alerts"
            continue

        logger.info(f"--- New Alert! ---\n{alert}")
        logger.info("Scraping images and info from NOAA CIMSS page...")

        alert_html_soup = scrape_cimss_alert(alert)
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

        if force_flag:
            messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

        logger.info("Posting to mattermost...")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
        # send to other mm channels based on alert type and volcano status
        cimss_mm_channels(alert, config, subject, message, filename, test_flag, mm_flag)
        # change mm channel id back to default
        config.mattermost_channel_id = default_mm_id
        alarming.record_send(
                config,
                T0,
                volcano=alert.v_name,
                event_id=alert.NOAA_id,
                test=test_flag,
            )

        state = "CRITICAL"
        state_message = f"{T0_str} (UTC) {subject}"

        if filename:
            os.remove(filename)

        # if not force_flag:
        #     processing.write_to_csv(cimss_df, config, outfile_columns)

    messaging.icinga(config, state, state_message, send=icinga_flag)
