import re

from obspy import UTCDateTime

from volc_alarms.utils import alarming, messaging, processing
from volc_alarms.utils.alarm_flow import run_send_sequence
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import download_SO2, get_so2_images
from .figure import plot_fig
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    table, soup = download_SO2()

    if table is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    try:
        table = table.get_text().split('\n')
        table = table[1:-1]

        date = table[1].split(":")[-1].replace(" ", "")
        time = table[2].split(" :")[-1].split("UTC")[0].replace(" ", "")

        lat_str = table[4].split(":")[-1]
        lon_str = table[3].split(":")[-1]
        lat, lat_dir = re.findall(r"(\d+\.\d+)\s{1}(\S{1})", lat_str)[0]
        lon, lon_dir = re.findall(r"(\d+\.\d+)\s{1}(\S{1})", lon_str)[0]
        lat = float(lat)
        lon = float(lon)
        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        volcs = load_volcano_list()
        volcs = processing.volcano_distance(lon, lat, volcs, filter_col="SO2")


        # lon    = float(table[3].split(':')[-1].split('deg')[0].replace(' ',''))
        # lat    = float(table[4].split(':')[-1].split('deg')[0].replace(' ',''))
        # SZA    = table[4].split(':')[-1].split('deg')[0].replace(' ','')
        # SO2max = table[5].split(':')[-1].split('DU')[0].replace(' ','')
        # S02ht  = table[6].split(':')[-1].split('km')[0].replace(' ','')
    except Exception:
        logger.warning("Page error.")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)	
        return	


    volcano_name = volcs.loc[volcs["distance"].idxmin()].Name
    alert_time = UTCDateTime(date + time).strftime("%Y-%m-%d %H:%M:%S")
    event_id = f"{volcano_name} - {alert_time}"
    new_alert = alarming.already_processed(config, event_id, test=test_flag)

    if new_alert and volcs.distance.min() < config.max_distance:

        logger.info(f"....New detection at {volcano_name}....")
        state = "CRITICAL"
        state_message = f"{T0_str} (UTC) SO2 detection!"

        def _so2_figure():
            logger.info("Downloading image")
            try:
                get_so2_images(soup, config)
            except Exception:
                logger.warning("Problem downloading images.")
            logger.info("Trying to make figure attachment")
            return plot_fig(config)

        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=_so2_figure,
            message_factory=lambda: create_message(date, alert_time, table, config, volcs),
            record_kwargs={"volcano": volcano_name, "event_id": event_id},
            send_email=False,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )
    elif volcs.distance.min() < config.max_distance and not new_alert:
        state_message = f"{T0_str} (UTC) Old SO2 detection! [{alert_time}]"
        state = "WARNING"
    else:
        state_message = f"{T0_str} (UTC) No new SO2 detections"
        state = "OK"

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
