import traceback

import numpy as np

from volc_alarms.utils import downloading, messaging
from volc_alarms.utils.alarm_flow import apply_cron_latency_backup, run_send_sequence
from volc_alarms.utils.setup_utils import get_logger

from .detection import RSAM_to_DR
from .figure import make_figure
from .message import create_message

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0 = apply_cron_latency_backup(config, T0)
    state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"

    if force_flag:
        logger.warning("Forcing trigger by setting min_sta = 0")
        config.min_sta = 0

    all_stas = config.rsam_stations + [config.arrestor]
    nslc = [sta["nslc"] for sta in all_stas]
    lvlv = np.array([sta["value"] for sta in all_stas])
    stas = [sta.split(".")[1] for sta in nslc]

    t1 = T0 - config.duration
    t2 = T0
    st = downloading.download_waveforms(nslc, t1, t2, fill_value=0)

    #### preprocess data ####
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper)
    st.filter("bandpass", freqmin=config.f1, freqmax=config.f2)

    #### calculate rsam ####
    rms = np.array([np.sqrt(np.mean(np.square(tr.data))) for tr in st])

    #### calculate reduced displacement ####
    DR = []
    try:
        if hasattr(config, "volcano_name"):
            DR = np.array([RSAM_to_DR(tr, config.volcano_name) for tr in st])
            logger.info("Successfully calculated Reduced Displacement")
    except Exception as e:
        logger.warning(e)
        logger.error(traceback.format_exc())
        pass

    ############################# Icinga message #############################
    if any(DR):
        state_message = "".join(
            f"{sta}: {rms[i]:.0f}/{lvlv[i]:.0f} (RD = {DR[i]:.1f}), "
            for i, sta in enumerate(stas[:-1])
        )
    else:
        state_message = "".join(
            f"{sta}: {rms[i]:.0f}/{lvlv[i]:.0f}, " for i, sta in enumerate(stas[:-1])
        )
    state_message = "".join([state_message, f"Arrestor ({stas[-1]}): {rms[-1]:.0f}/{lvlv[-1]:.0f}"])
    state_message = "".join([state_message, f"[{config.min_sta:.0f} station minimum,{config.f1:g} -- {config.f2:g} Hz]"])
    ###########################################################################

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    if (rms[-1] < lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1]) >= config.min_sta):
        #### RSAM Detection!! ####
        logger.info("********** DETECTION **********")
        state_message = f"{T0_str} (UTC) RSAM detection! {state_message}"
        state = "CRITICAL"

    elif (rms[-1] < lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1] / 2) >= config.min_sta):
        #### elevated RSAM ####
        state_message = f"{T0_str} (UTC) RSAM elevated! {state_message}"
        state = "WARNING"

    elif sum(rms[:-1] != 0) < config.min_sta:
        #### not enough data ####
        state_message = f"{T0_str} (UTC) RSAM data missing! {state_message}"
        state = "WARNING"

    elif (rms[-1] >= lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1]) >= config.min_sta):
        ### RSAM arrested ###
        state_message = f"{T0_str} (UTC) RSAM normal (arrested). {state_message}"
        state = "WARNING"

    else:
        #### RSAM normal ####
        state_message = f"{T0_str} (UTC) RSAM normal. {state_message}"
        state = "OK"

    if state == "CRITICAL":
        if hasattr(config, "infrasound"):
            nslc[-1:len(config.infrasound)] = config.infrasound
        run_send_sequence(
            config,
            T0,
            state,
            state_message,
            figure_factory=lambda: make_figure(nslc, T0, config, test=test_flag),
            message_factory=lambda: create_message(t1, t2, stas, rms, lvlv, DR, config.alarm_name),
            can_send_kwargs={},
            record_kwargs={},
            mm_flag=mm_flag,
            icinga_flag=icinga_flag,
            test_flag=test_flag,
        )
        return

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)
