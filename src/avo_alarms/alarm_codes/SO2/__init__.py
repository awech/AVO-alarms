import os
import traceback
import re

from obspy import UTCDateTime

from avo_alarms.utils import messaging, processing, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

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
        volcs = volcs[volcs["SO2"] == "Y"]
        volcs = processing.volcano_distance(lon, lat, volcs)
        volcs = volcs.sort_values("distance")


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


    volcano_name = volcs.iloc[0].Name
    alert_time = UTCDateTime(date + time).strftime("%Y-%m-%d %H:%M:%S")
    event_id = f"{volcano_name} - {alert_time}"
    new_alert = alarming.already_processed(config, event_id, test=test_flag)

    if new_alert and volcs.distance.min() < config.max_distance:

        logger.info(f"....New detection at {volcano_name}....")

        logger.info("Downloading image")
        try:
            get_so2_images(soup, config)
        except Exception:
            logger.warning("Problem downloading images.")

        logger.info("Trying to make figure attachment")
        try:
            filename = plot_fig(config)
            logger.info("Figure generated successfully")
        except Exception:
            filename = []
            logger.error("Problem making figure. Continue anyway")
            b = traceback.format_exc()
            err_message = "".join(f"{a}\n" for a in b.splitlines())
            logger.error(err_message)
            pass

        
        logger.info("Drafting alert")
        subject, message = create_message(date, alert_time, table, config, volcs)

        # logger.info("Sending direct alert")
        # messaging.send_alert(
        #     config.alarm_name, subject, message, attachment=filename, test=test_flag
        # )


        logger.info("Posting to Mattermost")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
        alarming.record_send(config, T0, volcano=volcano_name, event_id=event_id, test=test_flag)

        # delete the file you just sent
        if filename:
            os.remove(filename)

        state_message = f"{T0_str} (UTC) SO2 detection!"
        state = "CRITICAL"
    elif volcs.distance.min() < config.max_distance and not new_alert:
        state_message = f"{T0_str} (UTC) Old SO2 detection! [{alert_time}]"
        state = "WARNING"
    else:
        state_message = f"{T0_str} (UTC) No new SO2 detections"
        state = "OK"

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
