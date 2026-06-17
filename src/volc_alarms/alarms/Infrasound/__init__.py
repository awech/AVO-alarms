import numpy as np
from obspy import Stream

from volc_alarms.utils import messaging, processing, downloading, alarming
from volc_alarms.utils.alarm_flow import apply_cron_latency_backup, run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from . import detection, figure, message
from .figure import make_figure
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0 = apply_cron_latency_backup(config, T0)
    state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"

    #### download data ####
    t1 = T0 - config.duration
    t2 = T0
    st = downloading.download_waveforms(list(config.nslc), t1, t2, fill_value=0)
    st = processing.add_metadata(st)

    #### check for enough data ####
    for tr in st:
        if np.sum(np.abs(np.abs(tr.data))) == 0:
            st.remove(tr)
    if len(st) < config.min_chan:
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
    if len(st) < config.min_chan and not force_flag:
        state_message = f"{state_message} - Gappy data!"
        logger.warning(state_message)
        state = "WARNING"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### preprocess data ####
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper_val)
    st.filter("bandpass", freqmin=config.f1, freqmax=config.f2)
    for tr in st:
        if tr.stats["sampling_rate"] == 100:
            tr.decimate(2)
        if tr.stats["sampling_rate"] != 50:
            tr.resample(50.0)
        tr.remove_sensitivity(tr.inventory)

    #### check amplitude threshold ####
    if force_flag:
        logger.warning("Running in force trigger mode")
        min_pa = 0
    else:
        min_pa = np.array([v["min_pa"] for v in config.targets]).min()
    st = Stream([tr for tr in st if np.any(np.abs(tr.data) > min_pa)])
    if len(st) < config.min_chan and not force_flag:
        state_message = f"{state_message} - not enough channels exceeding amplitude threshold!"
        logger.info(state_message)
        state = "OK"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### Set up grid ####
    config = detection.get_target_backazimuth(st, config)
    yx, intsd, ints_az = detection.setup_coordinate_system(st)
    #### Cross correlate ####
    lags, lags_inds1, lags_inds2 = detection.calc_triggers(st, config, intsd, force=force_flag)
    cmbm2, cmbm2n, counter, mpk = detection.associator(lags_inds1, lags_inds2, st, config)

    if counter == 0:
        state_message = f"{state_message} - alarm normal."
        state = "OK"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### some event detected...determine velocity and azimuth ####
    velocity, azimuth, rms = detection.inversion(
        cmbm2n, cmbm2, intsd, ints_az, lags_inds1, lags_inds2, lags, mpk
    )
    d_Azimuth = azimuth - np.array([t["back_azimuth"] for t in config.targets])
    az_tolerance = np.array([t["az_tolerance"] for t in config.targets])
    #### check if this is airwave velocity from a target in config file list ####
    if np.any(np.abs(d_Azimuth) < az_tolerance) or force_flag:
        v_ind = np.argmin(np.abs(d_Azimuth))
        mx_pressure = np.max(np.array([np.max(np.abs(tr.data)) for tr in st]))
        if (
            config.targets[v_ind]["vmin"] < velocity < config.targets[v_ind]["vmax"]
            and mx_pressure > config.targets[v_ind]["min_pa"]
        ) or force_flag:
            #### DETECTION ####
            target = config.targets[v_ind]
            d_Azimuth = d_Azimuth[v_ind]

            logger.info("Airwave Detection!!!")
            state_message = f"{state_message} - {target['name']} detection! {mx_pressure:.1f} Pa peak pressure"
            state = "CRITICAL"

        else:
            logger.info("Non-volcano detect!!!")
            state_message = f"{state_message} - Detection with wrong velocity ({velocity:.1f} km/s) or maximum pressure ({mx_pressure:.1f} Pa)"
            state = "WARNING"
    else:
        #### trigger, but not from volcano ####
        logger.info("Non-volcano detect!!!")
        state_message = f"{state_message} - Detection with wrong backazimuth ({azimuth:.0f} from N)"
        state = "WARNING"

    if state == "CRITICAL":
        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda: make_figure(st, target, T0, config, mx_pressure, test=test_flag),
            message_factory=lambda: create_message(t1, t2, st, target, azimuth, d_Azimuth, velocity, mx_pressure),
            can_send_kwargs={"volcano": target["name"]},
            record_kwargs={"volcano": target["name"]},
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )
        return

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
