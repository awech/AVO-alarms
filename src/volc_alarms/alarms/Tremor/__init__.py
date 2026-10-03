"""
Tremor alarm.

Downloads waveform data for a set of stations, builds band-passed and
high-passed envelopes, and locates tremor/swarm sources via ``enveloc``
cross-correlation. New locations are merged with recent events from the
database and the total seismicity duration over the lookback window is
computed. Duration (and an optional RSAM amplitude gate) classify the result:
a sustained detection with new events escalates to CRITICAL and sends an alert
with a spectrogram figure and message, while lesser conditions map to
elevated, low-amplitude, missing-data, or normal states.

The package exposes :func:`run_alarm`, the entry point invoked by
``run-alarm`` for configs whose ``alarm_type`` is ``Tremor``.
"""

import numpy as np
import pandas as pd

from volc_alarms.utils import alarming, downloading, messaging, processing
from volc_alarms.utils.alarm_flow import apply_cron_latency_backup, run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from . import detection, figure, message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):
    """Run the Tremor alarm for one time window.

    Downloads and preprocesses station data for the window, QC-checks station
    coverage, optionally applies an RSAM amplitude gate, and locates
    tremor/swarm sources with ``enveloc``. New locations are merged with recent
    events from the database, the total seismicity duration over the lookback
    window is computed, and the result is classified. A sustained detection
    with new events sends a CRITICAL alert; otherwise an Icinga heartbeat
    reports the elevated/low-amplitude/missing/normal state.

    Parameters
    ----------
    config : object
        Tremor alarm configuration (``nslc``, ``window_length``, ``taper``,
        ``lookback_window``, ``threshold``, ``min_sta``, grid settings, and
        optional ``rsam_station``/``rsam_threshold``).
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
        Reserved for forcing behavior during testing, by default False.

    Returns
    -------
    None
        Returns after sending the alert (on a CRITICAL detection) or after the
        Icinga heartbeat otherwise.
    """

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    state_message = f"{T0_str} (UTC)"

    T0 = apply_cron_latency_backup(config, T0, extra_sleep=config.taper)

    state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"

    table_name = alarming.resolve_table_name(test_flag, table="tremor")
    db_conn = alarming.get_conn(test=test_flag, table="tremor")
    tremor_df = pd.read_sql_query(
        f"SELECT * FROM {table_name}",
        db_conn,
        parse_dates=["time"],
        dtype={
            "latitude": float,
            "longitude": float,
        },
    )
    tremor_df['time'] = tremor_df['time'].dt.tz_localize(None)

    ######### download data #########
    nslc = list(config.nslc)
    t1 = T0 - 1.5 * config.window_length - config.taper
    t2 = T0 + config.taper
    st = downloading.download_waveforms(nslc, t1, t2)
    

    ######## preprocess data ########
    band_env, high_env, band = detection.preprocess(st, config, t1, t2)
    band = processing.add_metadata(band)
    band_env = processing.add_metadata(band_env)
    high_env = processing.add_metadata(high_env)

    if detection.qc_checks(band) < config.min_sta:
        state_message = f"{state_message} - Data missing!"
        state = "WARNING"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return
    
    ######### run rsam test #########
    if hasattr(config, "rsam_station") and hasattr(config, "rsam_threshold"):
        rsam_st = band.select(id=config.rsam_station)
        if rsam_st:
            rsam = np.sqrt(np.mean(np.square(rsam_st[0].data)))
            rsam_test = rsam
        else:
            rsam = 0
            rsam_test = config.rsam_threshold + 1  # test sta missing, ensure alarm can still fire
            subject = f"{config.alarm_name} error"
            msg = (
                f"RSAM test station: {config.rsam_station} is missing. Consider replacing"
            )
            messaging.send_alert("Error", subject, msg)  # warn of missing station
    else:
        # No RSAM gate configured — always pass
        rsam = 0
        rsam_test = np.inf
        config.rsam_threshold = 0
    #################################

    ######### get locations #########
    logger.info("Running enveloc")
    loc = detection.run_enveloc(st, band_env, high_env, config)
    #################################

    ##### merge new event with old events #####
    locs_dict = {
        "time": [pd.to_datetime(location.starttime.datetime) for location in loc.events],
        "latitude": np.round(loc.get_lats(), 5),
        "longitude": np.round(loc.get_lons(), 5),
        "depth": np.round(loc.get_depths(), 2),
    }
    new_tremor_df = pd.DataFrame(locs_dict)
    new_tremor_df["volcano"] = config.volcano
    tremor_df = pd.concat([tremor_df, new_tremor_df]).drop_duplicates("time")
    T1 = pd.to_datetime(T0.datetime) - pd.to_timedelta(config.lookback_window, "min")
    T2 = pd.to_datetime(T0.datetime)
    tremor_df = tremor_df.drop_duplicates(subset="time")
    tremor_df = tremor_df[tremor_df["time"] >= T1]
    tremor_df = tremor_df[tremor_df["time"] <= T2]

    #### calculate total tremor/swarm duration ####
    num_overlap = len(
        np.where(np.diff(tremor_df["time"].values))[0] == config.window_length / 2
    )
    duration = (
        config.window_length * len(tremor_df) - (config.window_length / 2) * num_overlap
    ) / 60

    ####### set icinga status #######
    duration_text, recency_text = detection.create_icinga_test(tremor_df, T0, duration, rsam, config)

    if duration < config.threshold / 2:
        state_message = f"{state_message} Seismicity normal. {duration_text} {recency_text}"
        state = "OK"
        logger.info(state_message)
    elif duration >= config.threshold / 2 and duration < config.threshold:
        state_message = f"{state_message} Elevated seismicity. {duration_text} {recency_text}"
        state = "WARNING"
        logger.info(state_message)
    elif duration >= config.threshold and rsam_test < config.rsam_threshold:
        state_message = f"{state_message} Tremor/Swarm detection, but low amplitude. {duration_text} {recency_text}"
        state = "WARNING"
        logger.info(state_message)
    else:
        # elevated seismicity but no new events
        if len(loc.events) == 0:
            logger.warning("elevated seismicity but no new events")
            state_message = f"{state_message} Tremor/Swarm detection! {duration_text} {recency_text}"
            state = "WARNING"
            logger.info(state_message)
        # elevated seismicity + new events
        else:
            logger.info("Elevated Seismicity. New event(s) detected!")
            state_message = f"{state_message} Tremor/Swarm detection! {duration_text} {recency_text}"
            state = "CRITICAL"

            run_send_sequence(
                config,
                T0,
                state,
                state_message,
                figure_factory=lambda: figure.make_figure(nslc, T0, config, test=test_flag),
                message_factory=lambda: message.create_message(T0 - config.lookback_window * 60, T0, config.alarm_name, duration_text),
                record_kwargs={"volcano": config.volcano},
                can_send_kwargs={},
                mm_flag=mm_flag,
                icinga_flag=icinga_flag,
                test_flag=test_flag,
            )

            # update catalog in the database
            alarming.record_tremor_event_ids(tremor_df, test=test_flag)
            return
    #################################

    # update catalog in the database
    alarming.record_tremor_event_ids(tremor_df, test=test_flag)

    # update icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
