import numpy as np
from obspy import Stream

from volc_alarms.utils import messaging, processing, downloading
from volc_alarms.utils.alarm_flow import apply_cron_latency_backup, run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from . import detection
from .figure import make_figure
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0 = apply_cron_latency_backup(config, T0)
    t1 = T0 - config.duration
    t2 = T0
    state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"


    #### download data ####
    st = downloading.download_waveforms(config.nslc, t1-config.taper, t2+config.taper)
    st = processing.add_metadata(st)


    #### preprocess data ####
    st = processing.preprocess_stream(st, t1, t2, config)
    for tr in st:
        tr.remove_sensitivity(tr.inventory)

    #### check for enough data ####
    for tr in st:
        if np.sum(np.abs(np.abs(tr.data))) == 0:
            st.remove(tr)
    if len(st) < config.min_channels:
        state_message = f"{state_message} - Not enough channels!"
        logger.warning(state_message)
        state = "WARNING"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    #### check for gappy data ####
    for tr in st:
        num_zeros = len(np.where(tr.data == 0)[0])
        if num_zeros / float(tr.stats.npts) > 0.01:
            st.remove(tr)
    if len(st) < config.min_channels and not force_flag:
        state_message = f"{state_message} - Gappy data!"
        logger.warning(state_message)
        state = "WARNING"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    #### check amplitude threshold ####
    if force_flag:
        logger.warning("Running in force trigger mode")
        min_pa = 0
    else:
        min_pa = np.array([v["min_pa"] for v in config.targets]).min()

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
    results_df, lts_dict = detection.do_LTS(st, config)
    
    for target in config.targets:
        target_df = detection.filter_lts_results(results_df, target)
        if len(target_df) > 0:
            logger.info("Airwave Detection!!!")
            state_message = f"{state_message} - {target['name']} detection! {target_df["Pressure"].max():.1f} Pa peak pressure"
            state = "CRITICAL"

            mx_pressure = target_df["Pressure"].max()
            velocity = target_df["Velocity"].mean() / 1000
            azimuth = target_df["Azimuth"].mean()
            d_Azimuth = azimuth - target["back_azimuth"]
            
            run_send_sequence(
                config,
                T0,
                state,
                state_message,
                figure_factory=lambda: make_figure(target, T0, config, mx_pressure, test=test_flag),
                message_factory=lambda: create_message(t1, t2, st, target, azimuth, d_Azimuth, velocity, mx_pressure),
                can_send_kwargs={"volcano": target["name"]},
                record_kwargs={"volcano": target["name"]},
                mm_flag=mm_flag,
                icinga_flag=icinga_flag,
                test_flag=test_flag,
            )

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
