# RSAM  alarm to be run on list of channels
# Based on MATLAB code originally written by Matt Haney and Aaron Wech
#
# Wech 2017-06-08

import os
import time

import matplotlib.pyplot as plt
import numpy as np
from pandas import DataFrame

from ..utils import messaging, plotting, processing
from ..utils.setup_utils import get_logger

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    if os.getenv("FROMCRON") == "yep":
        time.sleep(config.latency)

    if test_flag:
        config.min_sta = 0

    SCNL = DataFrame.from_dict(config.SCNL)
    lvlv = np.array(SCNL["value"])
    scnl = SCNL["scnl"].tolist()
    stas = [sta.split(".")[0] for sta in scnl]

    t1 = T0 - config.duration
    t2 = T0
    st = processing.grab_data(scnl, t1, t2, fill_value=0)

    #### preprocess data ####
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper_val)
    st.filter("bandpass", freqmin=config.f1, freqmax=config.f2)

    #### calculate rsam ####
    rms = np.array([np.sqrt(np.mean(np.square(tr.data))) for tr in st])

    #### calculate reduced displacement ####
    DR = []
    try:
        if hasattr(config, "VOLCANO_NAME"):
            DR = np.array([processing.RSAM_to_DR(tr, config.VOLCANO_NAME) for tr in st])
            logger.info("Successfully calculated Reduced Displacement")
    except:
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
    state_message = "".join([state_message,f"[{config.min_sta:.0f} station minimum,{config.f1:g} -- {config.f2:g} Hz]"])
    ###########################################################################

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    if (rms[-1] < lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1]) >= config.min_sta):
        #### RSAM Detection!! ####
        ##########################
        logger.info("********** DETECTION **********")
        state_message = f"{T0_str} (UTC) RSAM detection! {state_message}"
        state = "CRITICAL"
        #
    elif (rms[-1] < lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1] / 2) >= config.min_sta):
        #### elevated RSAM ####
        #######################
        state_message = f"{T0_str} (UTC) RSAM elevated! {state_message}"
        state = "WARNING"
        #
    elif sum(rms[:-1] != 0) < config.min_sta:
        #### not enough data ####
        #########################
        state_message = f"{T0_str} (UTC) RSAM data missing! {state_message}"
        state = "WARNING"
        #
    elif (rms[-1] >= lvlv[-1]) & (sum(rms[:-1] > lvlv[:-1]) >= config.min_sta):
        ### RSAM arrested ###
        #####################
        state_message = f"{T0_str} (UTC) RSAM normal (arrested). {state_message}"
        state = "WARNING"
        #
    else:
        #### RSAM normal ####
        #####################
        state_message = f"{T0_str} (UTC) RSAM normal. {state_message}"
        state = "OK"

    if state == "CRITICAL":
        #### Generate Figure ####
        try:
            filename = make_figure(scnl, T0, config)
        except:
            filename = None

        ### Craft message text ####
        subject, message = create_message(t1, t2, stas, rms, lvlv, DR, config.alarm_name)

        ### Send message ###
        try:
            mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
            message = f"{message}\n\n{mm_url}"
        except:
            logger.error("problem posting to mattermost")
            
        messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)
        # delete the file you just sent
        if filename:
            os.remove(filename)

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)


def create_message(t1, t2, stations, rms, lvlv, DR, alarm_name):

    # create the subject line
    subject=f"--- {alarm_name} ---"

    # create the text for the message you want to send
    message = f"{messaging.format_timestring(t1, t2)}\n\n"

    a = np.array([""] * len(rms[:-1]))
    a[np.where(rms > lvlv)] = "*"

    if any(DR):
        sta_message = "".join(
            f"{sta}{a[i]}: {rms[i]:.0f}/{lvlv[i]:.0f} (RD = {DR[i]:.1f})\n"
            for i, sta in enumerate(stations[:-1])
        )
    else:
        sta_message = "".join(
            f"{sta}{a[i]}: {rms[i]:.0f}/{lvlv[i]:.0f}\n"
            for i, sta in enumerate(stations[:-1])
        )
    sta_message = "".join(
        [sta_message, f"\nArrestor: {stations[-1]} {rms[-1]:.0f}/{lvlv[-1]:.0f}"]
    )
    message = "".join([message, sta_message])

    return subject, message


def make_figure(scnl, T0, config):

    #### grab data ####
    start = time.time()
    t_win = config.plot_duration if hasattr(config, "plot_duration") else 3600
    st = processing.grab_data(scnl, T0 - t_win, T0, fill_value="interpolate")
    end = time.time()
    logger.info(f"{end - start:.2f} seconds to grab figure data.")

    #### preprocess data ####
    st.detrend("demean")
    [tr.decimate(2, no_filter=True) for tr in st if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in st if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in st if tr.stats.sampling_rate != 25]

    #### generate the figure ####
    axes_list = [[f"{tr.stats.station}.{tr.stats.channel}"] for tr in st]
    fig, ax = plt.subplot_mosaic(axes_list, figsize=(4.5, 4.5))

    for i, tr in enumerate(st):
        name = f"{tr.stats.station}.{tr.stats.channel}"
        plotting.plot_spectrogram(ax[name], tr)
        plotting.format_spec_xaxis(ax[name], tr, st, i, config)

    plt.subplots_adjust(left=0.08, right=0.94, top=0.92, bottom=0.1, hspace=0.1)

    jpg_file = plotting.save_file(fig, config, dpi=250)

    return jpg_file
