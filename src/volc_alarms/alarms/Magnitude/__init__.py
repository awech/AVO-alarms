import os
import warnings

from volc_alarms.utils import messaging, processing, downloading, alarming
from volc_alarms.utils.setup_utils import get_logger

from .detection import process_event

logger = get_logger(__name__)

warnings.filterwarnings("ignore")


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    T2 = T0
    T1 = T2 - config.duration
    if force_flag:
        logger.warning("Forcing trigger by setting magmin = -5")
        config.magmin = -5

    URL = (
        f"{os.getenv('FDSN_URL')}"
        f"starttime={T1.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&endtime={T2.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&minmagnitude={config.magmin}"
        f"&maxdepth={config.maxdep}"
        f"&format=csv"
    )
    logger.info("Downloading events...")
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
    catalog_df = processing.find_nearest_volcano(catalog_df)
    catalog_df = catalog_df[catalog_df["v_distance"] < config.distance]

    # New events, but not close enough to volcanoes
    if len(catalog_df) == 0:
        logger.warning("Earthquakes detected, but not near any volcanoes")
        state = "OK"
        state_message = f"{T0_str} (UTC) No new earthquakes"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Compare old and new events
    N_new, N_old = alarming.check_new_event_ids(catalog_df["event_id"], test=test_flag)
    logger.info(f"Found {N_new} new and {N_old} old earthquakes")

    for i, row in catalog_df.iterrows():
        if alarming.already_processed(config, row.event_id, test=test_flag):
            logger.warning("Earthquakes detected, but already processed")
            state = "OK"
            state_message = f"{T0_str} (UTC) Old event detected"
            messaging.icinga(config, state, state_message, send=icinga_flag)
            continue

        logger.info(f"Processing event {row.event_id}")
        evt_url = f"{os.getenv('FDSN_URL')}eventid={row.event_id}"
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
            volcano=row.v_name,
        )
        alarming.record_send(
                config,
                T0,
                volcano=row.v_name,
                event_id=row.event_id,
                test=test_flag,
            )

        # delete the file you just sent
        if attachment:
            os.remove(attachment)

        state = "CRITICAL"
        eq_str = eq.preferred_origin().time.strftime("%Y-%m-%d %H:%M:%S")
        state_message = f"{eq_str} (UTC) {subject}"

    # if not force_flag:
    #     processing.write_to_csv(catalog_df, config, outfile_columns)
    messaging.icinga(config, state, state_message, send=icinga_flag)
