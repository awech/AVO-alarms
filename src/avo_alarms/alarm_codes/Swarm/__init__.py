import os
import traceback

import numpy as np
import pandas as pd

from avo_alarms.utils import downloading, messaging, processing, alarming
from avo_alarms.utils.setup_utils import get_logger

from .detection import get_swarms, check_swarm_continue, compare_swarms, build_download_url
from .figure import make_figure
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    # Download the event data
    T0_str = T0.strftime("%Y-%m-%d %H:%M")

    config.DURATION = np.array([swm['MAX_EVT_TIME'] for swm in config.swarm_parameters]).max()
    logger.info(f"Downloading events {config.DURATION:g}s before {T0_str}")
    URL = build_download_url(T0, config)
    eq_df = downloading.download_hypocenters_csv(URL)

    # Error pulling events
    if eq_df is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) FDSN connection error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Filter out regional events
    logger.info(f"{len(eq_df):g} earthquakes detected")
    logger.info("Filtering out regional VTs")
    eq_df = processing.find_nearest_volcano(eq_df)
    eq_df = eq_df[eq_df["v_distance"] < config.VOLCANO_DISTANCE]
    logger.info(f"{len(eq_df):g} earthquakes near volcanoes")

    # No quakes close enough to volcanoes
    if len(eq_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new swarm activity"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    new_eq_df, eq_df = alarming.filter_dataframe(eq_df, id_column="event_id", test=test_flag, table="swarm")
    table_name = alarming.resolve_table_name(test_flag, table="swarm")
    db_conn = alarming.get_conn(test=test_flag, table="swarm")
    old_eq_df = pd.read_sql_query(
        f"SELECT * FROM {table_name}",
        db_conn,
        parse_dates=["time"],
        dtype={
            "latitude": float,
            "longitude": float,
        },
    )
    old_eq_df['time'] = old_eq_df['time'].dt.tz_localize(None)
    old_eq_df['v_name'] = old_eq_df['volcano']


    # No new earthquakes
    if len(new_eq_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Check for swarms
    logger.info("Clustering...")
    swarms = get_swarms(new_eq_df, T0, config)
    swarm_continue = check_swarm_continue(T0, config, old_eq_df, new_eq_df)

    # New earthquakes, but not swarm-y
    if len(swarms) == 0 and len(swarm_continue) == 0:
        logger.warning("Earthquakes detected, but no new swarm actvity")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new swarm actvity"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # New earthquakes aren't swarm-y by themselves, but continuation of ongoing swarm
    elif len(swarms) == 0 and len(swarm_continue) > 0:
        logger.info("Earthquakes detected. Continuation of swarm actvity")
        state = "WARNING"
        v_list = [swarm.iloc[0].v_name for swarm in swarm_continue]
        v_list_txt = ", ".join(np.unique(v_list))
        state_message = f"{T0_str} (UTC) Ongoing swarm actvity at: {v_list_txt}"

        # Merge continued detects into one DataFrame
        merged_swarm = pd.concat(swarm_continue, ignore_index=True).drop_duplicates("event_id")
    else:
        # remove duplicate or overlapping swarms
        swarms = compare_swarms(swarms)

        for swarm in swarms:
            state = "CRITICAL"
            volcano = swarm.iloc[0].v_name
            state_message = f"{T0_str} (UTC) Swarm actvity at: {volcano}"

            subject, message = create_message(swarm)
            logger.info(subject)
            logger.info(message)

            #### Generate Figure ####
            try:
                filename = make_figure(swarm, T0, config, test=test_flag)
                swarm_t1 = swarm.time.min().strftime("%Y%m%d_%H%M")
                swarm_t2 = swarm.time.max().strftime("%Y%m%d_%H%M")
                new_filename = f"{volcano}_M{swarm_t1}-{swarm_t2}.png"
                filename = filename.rename(filename.parent / new_filename)
            except Exception as e:
                filename = []
                logger.error("Problem making figure. Continue anyway")
                logger.warning(e)
                logger.warning(traceback.format_exc())

            if test_flag:
                messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

            logger.info("Posting message to Mattermost...")
            messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag, volcano=volcano)
            # swarm_id = f"{volcano}-{T0_str}"
            alarming.record_send(config, T0, volcano, event_id=None, test=test_flag)

            if filename:
                os.remove(filename)

        # Merge swarms into single DataFrame
        merged_swarm = pd.concat(swarms, ignore_index=True).drop_duplicates("event_id")

    alarming.record_swarm_event_ids(merged_swarm, test=test_flag)
    messaging.icinga(config, state, state_message, send=icinga_flag)

    return
