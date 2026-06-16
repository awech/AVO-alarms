import os
import traceback
import warnings

import pandas as pd

from avo_alarms.utils import messaging, processing, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import download_lightning, inner_outer, get_state_message
from .figure import plot_fig
from .message import create_message

warnings.filterwarnings("ignore")
logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    ### get alerts from volcview api
    strokes_df = download_lightning(force=force_flag)
    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    T1 = pd.to_datetime(T0_str) - pd.to_timedelta(config.duration, "s")

    if strokes_df is None:
        logger.error("Error downloading lightning data from API")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) Error getting data from Volcview-API"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    if len(strokes_df) == 0:
        logger.info("No new lightning strokes detected")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new strokes detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    strokes_df = strokes_df[strokes_df["time"] > T1.strftime("%Y-%m-%d %H:%M:%S")]

    if test_flag:
        strokes_df["v_distance"] = strokes_df["api_vdist"]
        strokes_df["v_name"] = strokes_df["api_vname"]
    else:
        volcs = load_volcano_list()
        volcs = volcs[volcs["Lightning"] == "Y"]
        strokes_df = processing.find_nearest_volcano(
            strokes_df,
            volc_df=volcs,
        )

    strokes_df = strokes_df[strokes_df["v_distance"] < config.dist2]
    new_strokes_df, strokes_df = alarming.filter_dataframe(strokes_df, id_column="id", test=test_flag)
    logger.info(
        f"{len(new_strokes_df)} new and {len(strokes_df) - len(new_strokes_df)} old strokes detected."
    )

    if len(new_strokes_df) == 0:
        logger.info("No lightning detected")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new strokes detected"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    volcanoes = new_strokes_df.v_name.unique()
    if force_flag:
        volcanoes = [volcanoes[0]]
    N_v = len(volcanoes)
    logger.info(f"Lightning detected at {N_v:.0f} volcano{'' if N_v==1 else 'es'}")
    for v_name in volcanoes:
        if not v_name:
            logger.warning("Null volcano. Skipping...")
            continue

        logger.info(f"--- Processing detects at {v_name} volcano ---")
        v_strokes = strokes_df[strokes_df["v_name"] == v_name]
        new_v_strokes, v_strokes = alarming.filter_dataframe(v_strokes, id_column="id", test=test_flag)
        n_ring1, n_ring2 = inner_outer(new_v_strokes, config)

        if len(new_v_strokes) == 0:
            logger.info("Old detection already processed")
            state = "WARNING"
            state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)
        else:
            logger.info("**** NEW DETECTION")
            new_v_strokes = new_v_strokes.sort_values("time")
            logger.info(
                f"{len(new_v_strokes)} new and {len(v_strokes) - len(new_v_strokes)} old strokes detected."
            )
            if new_v_strokes.iloc[0].v_distance > config.dist1:
                logger.info("...distal detection 1st.")
                state = "WARNING"
                state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)
            else:
                logger.info('**** PROXIMAL DETECTION 1st')
                state = "CRITICAL"
                state_message = get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config)

                ### Send Email Notification ####
                logger.info("Crafting message...")
                subject, message = create_message(new_v_strokes, v_strokes)
                try:
                    filename = plot_fig(v_strokes, config, T0, test=test_flag)
                except Exception as e:
                    logger.error("Error generating figure...")
                    logger.error(e)
                    logger.error(traceback.format_exc())
                    filename = None

                try:
                    logger.info("Sending message to mattermost")
                    mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
                    message = f"{message}\n\n{mm_url}"
                except Exception as e:
                    logger.error("problem posting to mattermost")
                    logger.error(e)
                    logger.error(traceback.format_exc())

                messaging.send_alert(
                    config.alarm_name,
                    subject,
                    message,
                    attachment=filename,
                    test=test_flag,
                )
                alarming.record_send(
                    config,
                    T0,
                    volcano=new_v_strokes.iloc[0].v_name,
                    event_id=new_v_strokes.id.to_list(),
                    test=test_flag,
                )
                # delete the file you just sent
                if filename:
                    os.remove(filename)

    messaging.icinga(config, state, state_message, send=icinga_flag)
