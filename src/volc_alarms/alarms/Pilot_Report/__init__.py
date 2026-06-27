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

    T0_str = T0.strftime("%Y-%m-%d %H:%M")

    state, archive = download_pilot_reports(T0, config)
    state_message = f"{T0_str} (UTC) No new pilot reports"
    if archive is None:
        if state == "WARNING":
            state_message = f"{T0_str} (UTC) PIREP API error. Cannot retrieve shape file"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    pirep_df = pirep_archive_to_dataframe(T0, config, archive)
    pirep_df = processing.find_nearest_volcano(pirep_df, lon_col="lon", lat_col="lat")
    pirep_df = pirep_df[pirep_df["v_distance"] < config.max_distance]

    ## BUG 'PROD_ID' is not entirely unique. See events at 2026-05-21 17:08 and 17:09
    N_new, N_old = alarming.check_new_event_ids(pirep_df["PROD_ID"], test=test_flag)
    logger.info(f"Found {N_new} new and {N_old} old PIREPS")

    if force_flag:
        pirep_df = pirep_df[:1]
    else:
        pirep_df = check_volcano_mention(pirep_df)
        pirep_df = pirep_df[pirep_df["trigger"]]

    for i, row in pirep_df.iterrows():

        if alarming.already_processed(config, row.PROD_ID, test=test_flag):
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
            record_kwargs={"volcano": row.v_name, "event_id": row.PROD_ID},
            send_email=is_critical,
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )

    # if not force_flag:
    #     processing.write_to_csv(pirep_df, config, outfile_columns)
    messaging.icinga(config, state, state_message, send=icinga_flag)

    return
