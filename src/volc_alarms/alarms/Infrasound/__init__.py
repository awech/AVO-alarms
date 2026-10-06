"""
Infrasound airwave-detection alarm.

Downloads and conditions infrasound array data, runs least-trimmed-squares
(LTS) array processing to estimate back-azimuth and trace velocity, and
compares the results against each configured volcano target. When a target's
filters are satisfied, it issues an airwave-detection alert with a figure and
message.

The package exposes :func:`run_alarm`, the entry point invoked by
``run-alarm`` for configs whose ``alarm_type`` is ``Infrasound``.
"""

import numpy as np
from obspy import Stream

from volc_alarms.utils import downloading, messaging, processing
from volc_alarms.utils.alarm_flow import apply_cron_latency_backup, run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from . import detection
from .figure import make_figure
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):
    """Run the Infrasound airwave-detection alarm for one time window.

    Downloads array data ending at ``T0``, preprocesses it, runs quality
    control, removes gain (using manual metadata or StationXML), checks the
    amplitude threshold, then performs LTS array processing. For each
    configured target whose filtered results indicate an airwave, sends an
    alert via the shared send sequence. An Icinga heartbeat is always sent.

    Parameters
    ----------
    config : object
        Infrasound alarm configuration (channels, targets, LTS parameters,
        thresholds, etc.).
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
        Force a detection regardless of thresholds, using only the first
        target, by default False.

    Returns
    -------
    None
        Returns early (after an Icinga heartbeat) when data quality or
        amplitude checks fail; otherwise returns after processing all targets.
    """
    T0 = apply_cron_latency_backup(config, T0)
    t1 = T0 - config.duration
    t2 = T0
    state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"
    state = "OK"

    #### download data ####
    nslc_list = list(config.nslc)  # works for both list and dict (manual metadata in .yml file)
    st = downloading.download_waveforms(nslc_list, t1-config.taper, t2+config.taper)

    #### preprocess data ####
    st = processing.preprocess_stream(st, t1, t2, config)

    # Check data quality
    good_data, skip_chans = detection.QC_data(st, config)
    if not good_data:
        state_message = f"{state_message} - Not enough channels!"
        logger.warning(state_message)
        state = "WARNING"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    # Add coordinates/inventory metadata, then remove gain
    st = Stream([tr for tr in st if tr.id not in skip_chans])
    if isinstance(config.nslc, dict):
        # Manual metadata from config: attach coordinates and divide by gain
        for tr in st:
            params = config.nslc[tr.id]
            tr.stats.coordinates = {"latitude": params["lat"], "longitude": params["lon"], "elevation": 0.0}
            tr.data = tr.data / params["gain"]
    else:
        # Lookup from station XML
        st = processing.add_metadata(st)
        st = processing.remove_gain(st)

    #### check amplitude threshold ####
    min_pa = np.array([v["min_pa"] for v in config.targets]).min()
    if force_flag:
        logger.warning("Running in force trigger mode")
        min_pa = 0

    st_test = Stream([tr for tr in st if np.any(np.abs(tr.data) > min_pa)])
    if len(st_test) < config.min_channels and not force_flag:
        state_message = f"{state_message} - not enough channels exceeding amplitude threshold!"
        logger.info(state_message)
        state = "OK"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### Add volcano backazimuths ####
    config = detection.get_target_backazimuth(st, config)

    #### invert for velocity and back-azimuth ####
    results_df, _lts_dict = detection.do_LTS(st, config)

    if force_flag:
        config.targets = [config.targets[0]]

    for target in config.targets:
        target_df = detection.filter_lts_results(results_df, target)
        if len(target_df) == 0 and force_flag:
            logger.warning(
                "Force mode: no windows passed target filters; "
                "using unfiltered LTS results for summary stats."
            )
            target_df = results_df
        if len(target_df) > 0 or force_flag:
            logger.info("Airwave Detection!!!")
            state_message = f"{state_message} - {target['name']} detection! {target_df['Pressure'].max():.1f} Pa peak pressure"
            state = "CRITICAL"

            mx_pressure = np.nanmax(target_df["Pressure"])
            velocity = np.nanmean(target_df["Velocity"]) / 1000
            azimuth = np.nanmean(target_df["Azimuth"])
            d_Azimuth = azimuth - target["back_azimuth"]

            run_send_sequence(
                config,
                T0,
                state,
                state_message,
                figure_factory=lambda target=target, mx_pressure=mx_pressure: make_figure(
                    target, T0, config, mx_pressure, test=test_flag
                ),
                message_factory=lambda target=target, azimuth=azimuth, d_Azimuth=d_Azimuth, velocity=velocity, mx_pressure=mx_pressure: create_message(
                    t1, t2, st, target, azimuth, d_Azimuth, velocity, mx_pressure
                ),
                can_send_kwargs={"volcano": target["name"]},
                record_kwargs={"volcano": target["name"]},
                mm_flag=mm_flag,
                icinga_flag=icinga_flag,
                test_flag=test_flag,
            )

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
