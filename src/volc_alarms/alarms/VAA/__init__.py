"""
Volcanic Ash Advisory (VAA) alarm.

Downloads the recent VAA advisory list from the Mesonet API, parses each text
advisory, associates it with the nearest volcano, and issues a CRITICAL alert
for any new advisory within the lookback window. Each alert includes a map of
the observed/forecast ash cloud polygons and a message reproducing the
advisory.

The package exposes :func:`run_alarm`, the entry point invoked by
``run-alarm`` for configs whose ``alarm_type`` is ``VAA``.
"""

import pandas as pd
from obspy import UTCDateTime

from volc_alarms.utils import alarming, messaging, processing
from volc_alarms.utils.alarm_flow import run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from .detection import download_mesonet_vaa_list, process_vaa_id
from .figure import make_map
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):
    """Run the Volcanic Ash Advisory alarm for one time window.

    Downloads the VAA advisory lists for the current and prior calendar day,
    parses each advisory, trims to the trailing ``config.duration`` window,
    de-duplicates, and associates each with the nearest volcano. For each new,
    unprocessed advisory, sends a CRITICAL alert. An Icinga heartbeat is sent
    for the no-advisory and already-processed cases.

    Parameters
    ----------
    config : object
        VAA alarm configuration (``duration`` and routing/figure settings).
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
        Force processing against a fixed historical timestamp for testing, by
        default False.

    Returns
    -------
    None
        Returns early (after an Icinga heartbeat) on download error or when no
        advisories are found; otherwise returns after looping over advisories.
    """
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
        if vaa is None:
            logger.warning("Skipping VAA that could not be downloaded")
            continue
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
        subject, message = create_message(row)
        state = "CRITICAL"
        state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) New {subject}"

        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda row=row: make_map(row, config, test=test_flag),
            message_factory=lambda subject=subject, message=message: (subject, message),
            record_kwargs={"volcano": row.v_name, "event_id": row.id},
            send_email=force_flag,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )
