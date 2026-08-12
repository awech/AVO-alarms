import warnings

from volc_alarms.utils import alarming, messaging, processing
from volc_alarms.utils.alarm_flow import run_send_sequence
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import (
    check_ignore_volcano,
    download_cimss_vv_api,
    format_cimss_dataframe,
    process_alert_soup,
    resolve_ignore_column,
    scrape_cimss_alert,
)
from .figure import plot_fig
from .message import cimss_extra_channels, create_message

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

        logger.info("Crafting message...")
        volcs = load_volcano_list()
        filter_col = resolve_ignore_column(alert.alert_type, volcs.columns)
        volcs = processing.volcano_distance(
            alert.lon_rc, alert.lat_rc, volcs, filter_col=filter_col
        )
        subject, message = create_message(alert, volcs, output_text)

        state = "CRITICAL"
        state_message = f"{T0_str} (UTC) {subject}"

        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda alert=alert: plot_fig(alert, config, test=test_flag),
            message_factory=lambda subject=subject, message=message: (subject, message),
            mm_kwargs={"channel_ids": cimss_extra_channels(alert, config)},
            record_kwargs={"volcano": alert.v_name, "event_id": alert.NOAA_id},
            send_email=force_flag,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )

    messaging.icinga(config, state, state_message, send=icinga_flag)
