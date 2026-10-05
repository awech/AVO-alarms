"""
Magnitude alarm.

Queries an FDSN event service for recent earthquakes above a magnitude
threshold and below a depth cap, keeps those near a volcano, and for each new
(not already processed) event sends a CRITICAL alert with a summary figure and
message. No-event, far-from-volcano, and already-processed cases report an
Icinga heartbeat; FDSN connection errors report a warning.

The package exposes :func:`run_alarm`, the entry point invoked by
``run-alarm`` for configs whose ``alarm_type`` is ``Magnitude``.
"""

import os
import warnings

from volc_alarms.utils import alarming, downloading, messaging, processing
from volc_alarms.utils.alarm_flow import run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from .detection import process_event

logger = get_logger(__name__)

warnings.filterwarnings("ignore")


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):
    """Run the Magnitude alarm for one time window.

    Downloads the FDSN event catalog for the ``config.duration`` window above
    ``config.magmin`` and shallower than ``config.maxdep``, filters to events
    within ``config.distance`` of a volcano, and processes each new event. New
    unprocessed events send a CRITICAL alert; other outcomes report an Icinga
    heartbeat.

    Parameters
    ----------
    config : object
        Magnitude alarm configuration (``duration``, ``magmin``, ``maxdep``,
        ``distance``, and routing settings).
    T0 : obspy.UTCDateTime
        End time of the processing window.
    test_flag : bool, optional
        Run in test mode (test tables/channels, TEST watermark), by default
        False.
    mm_flag : bool, optional
        Whether to post to Mattermost, by default True.
    icinga_flag : bool, optional
        Whether to send the Icinga heartbeat, by default True.
    force_flag : bool, optional
        Force a detection by lowering the magnitude minimum, by default False.

    Returns
    -------
    None
        Returns early (after an Icinga heartbeat) on connection error or when
        no qualifying events are found; otherwise returns after looping over
        events.
    """

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

        state = "CRITICAL"
        eq_str = eq.preferred_origin().time.strftime("%Y-%m-%d %H:%M:%S")
        state_message = f"{eq_str} (UTC) {subject}"

        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda attachment=attachment: attachment,
            message_factory=lambda subject=subject, message=message: (subject, message),
            mm_kwargs={"volcano": row.v_name},
            record_kwargs={"volcano": row.v_name, "event_id": row.event_id},
            send_email=test_flag,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
