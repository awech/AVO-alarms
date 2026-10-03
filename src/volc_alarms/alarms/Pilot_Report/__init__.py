"""
Pilot Report (PIREP) alarm.

Downloads recent pilot reports from the IEM API, keeps those near a volcano,
and flags reports whose text mentions volcanic activity. Each new, unprocessed
flagged report sends an alert (CRITICAL when the report is marked urgent,
otherwise WARNING) with a location figure and message. No-report and
already-processed cases report an Icinga heartbeat.

The package exposes :func:`run_alarm`, the entry point invoked by
``run-alarm`` for configs whose ``alarm_type`` is ``Pilot_Report``.
"""

from volc_alarms.utils import alarming, messaging, processing
from volc_alarms.utils.alarm_flow import run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from .detection import (
    check_volcano_mention,
    download_pilot_reports,
    pirep_archive_to_dataframe,
)
from .figure import plot_fig
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):
    """Run the Pilot Report alarm for one time window.

    Downloads PIREPs for the ``config.duration`` window, keeps those within
    ``config.max_distance`` of a volcano, and (unless forced) filters to
    reports mentioning volcanic activity. Each new, unprocessed report sends an
    alert; otherwise an Icinga heartbeat is sent.

    Parameters
    ----------
    config : object
        PIREP alarm configuration (``duration``, ``max_distance``, and routing
        settings).
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
        Force a detection on the first report, bypassing the volcano-mention
        filter, by default False.

    Returns
    -------
    None
        Returns early (after an Icinga heartbeat) on download error; otherwise
        returns after looping over reports.
    """

    T0_str = T0.strftime("%Y-%m-%d %H:%M")

    state, archive = download_pilot_reports(T0, config)
    state_message = f"{T0_str} (UTC) No new pilot reports"
    if archive is None:
        if state == "WARNING":
            state_message = f"{T0_str} (UTC) PIREP API error. Cannot retrieve shape file"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    pirep_df = pirep_archive_to_dataframe(T0, config, archive)
    pirep_df = processing.find_nearest_volcano(pirep_df, lon_col="lon", lat_col="lat", filter_col="PIREP")
    pirep_df = pirep_df[pirep_df["v_distance"] < config.max_distance]

    N_new, N_old = alarming.check_new_event_ids(pirep_df["event_id"], test=test_flag)
    logger.info(f"Found {N_new} new and {N_old} old PIREPS")

    if force_flag:
        pirep_df = pirep_df[:1]
    else:
        pirep_df = check_volcano_mention(pirep_df)
        pirep_df = pirep_df[pirep_df["trigger"]]

    for i, row in pirep_df.iterrows():

        if alarming.already_processed(config, row.event_id, test=test_flag):
            logger.info("PIREPS found have already been processed")
            state = "OK"
            state_message = f"{T0_str} (UTC) No new pilot reports"
            continue

        is_critical = row.URGENT == "T" or force_flag
        state = "CRITICAL" if is_critical else "WARNING"
        subject, message = create_message(row, config)
        state_message = message

        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda row=row: plot_fig(row, config, test=test_flag),
            message_factory=lambda subject=subject, message=message: (subject, message),
            record_kwargs={"volcano": row.v_name, "event_id": row.event_id},
            send_email=is_critical,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )

    messaging.icinga(config, state, state_message, send=icinga_flag)

    return
