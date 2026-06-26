import os
import traceback

import pandas as pd
from obspy import UTCDateTime

from volc_alarms.utils import alarming, messaging, processing
from volc_alarms.utils.setup_utils import get_logger

from .detection import download_mesonet_vaa_list, process_vaa_id
from .figure import make_map
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    logger.info(T0)
    T0_str = T0.strftime("%Y-%m-%d %H:%M")

    if force_flag:
        T0 = UTCDateTime("2026-03-09 17:05")

    # download yesterday & today (mesonet api uses calendar date queries)
    vaa_id_list_1 = download_mesonet_vaa_list(T0 - 86400)
    vaa_id_list_2 = download_mesonet_vaa_list(T0)
    if vaa_id_list_1 is not None and vaa_id_list_2 is not None:
        vaa_id_list = pd.concat([vaa_id_list_1, vaa_id_list_2])
    else:
        vaa_id_list = None

    if vaa_id_list is None:
        logger.warning("Page error.")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    vaas_found = []
    for i, vaa_id in vaa_id_list.iterrows():
        vaa = process_vaa_id(vaa_id)
        vaas_found.append(vaa)
    vaas_df = pd.DataFrame(vaas_found)

    if "time" in vaas_df.columns:
        T1 = T0 - config.duration
        T1 = pd.to_datetime(T1.datetime).tz_localize("UTC")
        T2 = pd.to_datetime(T0.datetime).tz_localize("UTC")
        vaas_df = vaas_df[vaas_df["time"] >= T1]
        vaas_df = vaas_df[vaas_df["time"] <= T2]


    if len(vaas_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new Volcanic Ash Advisories"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    vaas_df = vaas_df.sort_values("time")
    vaas_df = vaas_df.drop_duplicates(subset="id")
    vaas_df = processing.find_nearest_volcano(vaas_df, lon_col="lon", lat_col="lat")
    
    for i, row in vaas_df.iterrows():

        if alarming.already_processed(config, row.id, test=test_flag):
            logger.info("VAA has already been processed")
            state = "OK"
            state_message = f"{T0_str} (UTC) No Volcanic Ash Advisories."
            messaging.icinga(config, state, state_message, send=icinga_flag)
            continue

        logger.info("New VAA detected")

        try:
            filename = make_map(row, config, test=test_flag)
        except Exception as e:
            ## TODO filename still hase "SIGMET" in it
            filename = []
            logger.error("Problem making figure. Continue anyway")
            logger.error(e)
            logger.error(traceback.format_exc())
            
        subject, message = create_message(row)

        if force_flag:
            logger.info("Sending message...")
            messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

        logger.info("Checking mattermost send...")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
        alarming.record_send(config, T0, volcano=row.v_name, event_id=row.id, test=test_flag)

        # delete the file you just sent
        if filename:
            os.remove(filename)

        state = "CRITICAL"
        state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) New {subject}"
        
        messaging.icinga(config, state, state_message, send=icinga_flag)
