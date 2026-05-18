import math
import os
import time
import traceback
from itertools import combinations

import matplotlib.pyplot as plt
import numpy as np
from obspy import Stream, UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth
from obspy.signal.cross_correlation import correlate, xcorr_max
from pandas import DataFrame

from avo_alarms.utils import messaging, processing, plotting, downloading, alarming
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    if os.getenv("FROMCRON") == "yep":
        if config.latency < 30:
            time.sleep(config.latency)
        else:
            dt = math.ceil(config.latency / 60) * 60
            T0 = T0 - dt
            logger.info(f"Backing up {dt} seconds to align with minute marks")
    state_message=f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) {config.alarm_name}"

    #### download data ####
    NSLC = DataFrame.from_dict(config.NSLC)
    t1 = T0 - config.duration
    t2 = T0
    st = downloading.download_waveforms(NSLC["nslc"].tolist(), t1, t2, fill_value=0)
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
        min_pa = np.array([v["min_pa"] for v in config.VOLCANO]).min()
    st = Stream([tr for tr in st if np.any(np.abs(tr.data) > min_pa)])
    if len(st) < config.min_chan and not force_flag:
        state_message = f"{state_message} - not enough channels exceeding amplitude threshold!"
        logger.info(state_message)
        state = "OK"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### Set up grid ####
    config = get_volcano_backazimuth(st, config)
    yx, intsd, ints_az = setup_coordinate_system(st)
    #### Cross correlate ####
    lags, lags_inds1, lags_inds2 = calc_triggers(st, config, intsd, force=force_flag)
    cmbm2, cmbm2n, counter, mpk = associator(lags_inds1, lags_inds2, st, config)

    if counter == 0:
        state_message = f"{state_message} - alarm normal."
        state = "OK"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    #### some event detected...determine velocity and azimuth ####
    velocity, azimuth, rms = inversion(
        cmbm2n, cmbm2, intsd, ints_az, lags_inds1, lags_inds2, lags, mpk
    )
    d_Azimuth = azimuth - np.array([t["back_azimuth"] for t in config.VOLCANO])
    az_tolerance = np.array([t["Azimuth_tolerance"] for t in config.VOLCANO])
    #### check if this is airwave velocity from a volcano in config file list ####
    if np.any(np.abs(d_Azimuth) < az_tolerance) or force_flag:
        v_ind = np.argmin(np.abs(d_Azimuth))
        mx_pressure = np.max(np.array([np.max(np.abs(tr.data)) for tr in st]))
        if (
            config.VOLCANO[v_ind]["vmin"] < velocity < config.VOLCANO[v_ind]["vmax"]
            and mx_pressure > config.VOLCANO[v_ind]["min_pa"]
        ) or force_flag:
            #### DETECTION ####
            volcano = config.VOLCANO[v_ind]
            d_Azimuth = d_Azimuth[v_ind]

            logger.info("Airwave Detection!!!")
            state_message = f"{state_message} - {volcano['volcano']} detection! {mx_pressure:.1f} Pa peak pressure"
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
        if not alarming.can_send(config, volcano=volcano['volcano'], T0=T0, test=test_flag):
            logger.warning(f"Rate limit: skipping alarm {config.alarm_name} at {volcano['volcano']}")
            state_message = f"{state_message} (alarm skipped due to rate limit)"
            messaging.icinga(config, state, state_message, send=icinga_flag)
            return
        try:
            logger.info("generating figure")
            filename = make_figure(st, volcano, T0, config, mx_pressure, test=test_flag)
        except Exception as e:
            logger.error("problem generating figure")
            logger.error(e)
            logger.error(traceback.format_exc())
            filename=None

        subject, message = create_message(
            t1, t2, st, volcano, azimuth, d_Azimuth, velocity, mx_pressure
        )

        try:
            mm_url = messaging.post_mattermost(
                config,
                subject,
                message,
                attachment=filename,
                send=mm_flag,
                test=test_flag,
            )
            message = f"{message}\n\n{mm_url}"
        except Exception as e:
            logger.error("problem posting to mattermost")
            logger.error(e)
            logger.error(traceback.format_exc())
            

        messaging.send_alert(
            config.alarm_name, subject, message, attachment=filename, test=test_flag
        )
        alarming.record_send(config, T0, volcano=volcano['volcano'], test=test_flag)
        # delete the file you just sent
        if filename:
            os.remove(filename)

        ## inf_df = pd.append(inf_df, {"time":....})
        ## inf_df.to_csv(outfile, index=False)


    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)


def get_volcano_backazimuth(st, config):
    lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
    lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
    for volc in config.VOLCANO:
        if "back_azimuth" not in volc:
            tmp = gps2dist_azimuth(lat0, lon0, volc["v_lat"], volc["v_lon"])
            volc["back_azimuth"] = tmp[1]
    return config


def setup_coordinate_system(st):
    R = 6372.7976  # radius of the earth
    lons = np.array([tr.stats.coordinates.longitude for tr in st])
    lats = np.array([tr.stats.coordinates.latitude for tr in st])
    lon0 = lons.mean() * np.pi / 180.0
    lat0 = lats.mean() * np.pi / 180.0
    yx = R * np.array([lats * np.pi / 180.0 - lat0, (lons * np.pi / 180.0 - lon0) * np.cos(lat0)]).T

    intsd = np.zeros([len(lons), len(lons)])
    ints_az = np.zeros([len(lons), len(lons)])
    for ii in range(len(st[:-1])):
        for jj in range(ii + 1, len(st)):
            # intsd[i,j]=np.sqrt(np.square(yx[j][0]-yx[i][0])+np.square(yx[j][1]-yx[i][1]))
            tmp = gps2dist_azimuth(lats[ii], lons[ii], lats[jj], lons[jj])
            intsd[ii, jj] = tmp[0]
            ints_az[ii, jj] = tmp[1]

    return yx, intsd, ints_az


def calc_triggers(st, config, intsd, force=False):
    lags = np.array([])
    lags_inds1 = np.array([])
    lags_inds2 = np.array([])
    #### cross correlate all station pairs ####
    for ii in range(len(st[:-1])):
        for jj in range(ii + 1, len(st)):
            cc_vector = correlate(st[ii].data, st[jj].data, config.cc_shift_length)
            index, value = xcorr_max(cc_vector)
            #### if best xcorr value is negative, find the best positive one ####
            if value < 0:
                index = cc_vector.argmax() - config.cc_shift_length
                value = cc_vector.max()
            dt = index / st[0].stats.sampling_rate
            #### check that the best lag is at least the vmin value
            #### and check for minimum cross correlation value
            all_vmin = np.array([v["vmin"] for v in config.VOLCANO]).min()
            if (np.abs(dt) < intsd[ii, jj] / all_vmin and value > config.min_cc) or force:
                lags = np.append(lags, dt)
                lags_inds1 = np.append(lags_inds1, ii)
                lags_inds2 = np.append(lags_inds2, jj)

    #### return lag times, and
    return lags, lags_inds1, lags_inds2


def associator(lags_inds1, lags_inds2, st, config):
    #### successively try to associate, starting with all stations
    #### and quit at config.min_sta

    counter = 0
    mpk = len(st)

    while counter == 0 and mpk >= config.min_chan:
        cmbm = np.array(list(combinations(range(0, len(st)), mpk)))
        cntr = len(cmbm)
        # find how many relevant picks exist for all combinations of delay times
        ncntrm = np.zeros((mpk, mpk, cntr))

        for jj, trig in enumerate(lags_inds1):
            for ii in range(0, cntr):
                if (
                    np.sum(lags_inds1[jj] == cmbm[ii,]) == 1
                    and np.sum(lags_inds2[jj] == cmbm[ii,]) == 1
                ):
                    ind1 = (lags_inds1[jj] == cmbm[ii,]).argmax()
                    ind2 = (lags_inds2[jj] == cmbm[ii,]).argmax()
                    ncntrm[ind1, ind2, ii] = 1

        # if one of the row/column sums is at least 3, accept it
        cmbm2 = np.zeros((cntr, mpk))
        cmbm2n = np.zeros(cntr)

        for ii in range(cntr):
            if np.sum(np.sum(ncntrm[:, :, ii], 1) == 0) == 1:
                cmbm2[counter, :] = cmbm[ii, :]
                # total number of qualifying picks
                cmbm2n[counter] = np.sum(np.sum(ncntrm[:, :, ii], 1))
                counter = counter + 1
        # if no matches, decrement and try again
        if counter == 0:
            mpk = mpk - 1

    cmbm2 = cmbm2.astype("int")
    cmbm2n = cmbm2n.astype("int")

    return cmbm2, cmbm2n, counter, mpk


def inversion(cmbm2n,cmbm2,intsd,ints_az,lags_inds1,lags_inds2,lags,mpk):
    # for jj in range(counter):
    jj=0
    # the size of the dt and Dm3
    dt  = np.zeros(cmbm2n[jj])
    Dm3 = np.zeros((cmbm2n[jj],2))

    # initialize interstation distance and azimuth vectors
    ds = np.array([])
    az = np.array([])

    # grab interstation distance and azimuth for all pairs in this tuple
    for num,kk in enumerate(cmbm2[jj,range(0,mpk-1)]):
        for ii in cmbm2[jj,range(num+1,mpk)]:
            ds = np.append(ds,intsd[kk,ii])
            az = np.append(az,ints_az[kk,ii])

    # some counters to find if there is a match in the trgs vector
    mtrxc = 0
    dacnt = 0

    # all 5 may not exist
    for kk in range(0,mpk-1):
        for ii in range(kk+1,mpk):
            tmp=np.array([lags_inds1,lags_inds2]).T - np.repeat(np.array([cmbm2[jj,kk],cmbm2[jj,ii]],ndmin=2),len(lags_inds1),0)
            tmp=np.sum(np.abs(tmp),1)
            mmin = tmp.min()
            mloc = tmp.argmin()
            if mmin==0:
                dt[mtrxc] = lags[mloc]
                Dm3[mtrxc,:] = [ds[dacnt]*np.cos(az[dacnt]*(np.pi/180.0)) , ds[dacnt]*np.sin(az[dacnt]*(np.pi/180.0))]
                mtrxc=mtrxc+1
            dacnt=dacnt+1
    Dm3=Dm3/1000.0  # convert to kilometers

    # generalized inverse of slowness matrix
    Gmi = np.linalg.inv(np.matmul(Dm3.T,Dm3))
    # slowness - least squares
    sv = np.matmul(np.matmul(Gmi,Dm3.T),dt.T)
    # velocity from slowness
    velocity = 1/np.sqrt(np.square(sv[0])+np.square(sv[1]))
    # cosine and sine for backazimuth
    caz3 = velocity*sv[0]
    saz3 = velocity*sv[1]
    # 180 degree resolved backazimuth to source
    azimuth = np.arctan2(saz3,caz3)*(180/np.pi)
    if azimuth<0:
        azimuth=azimuth+360
    # rms
    rms = np.sqrt(np.mean(np.square(np.matmul(Dm3,sv)-dt.T)))

    return velocity, azimuth, rms


def xcorr_align_stream(st, config):

    shift_len = config.cc_shift_length
    shifts = []
    for i, tr in enumerate(st):
        c = correlate(st[0].data, tr.data, shift_len)
        a, b = xcorr_max(c)
        if b < 0:
            a = c.argmax() - shift_len
        shifts.append(a / tr.stats.sampling_rate)

    group_streams = Stream()
    T1 = st[0].copy().stats.starttime
    T2 = st[0].copy().stats.endtime
    for i, tr in enumerate(st):
        tr = tr.copy().trim(
            tr.stats.starttime - shifts[i],
            tr.stats.endtime - shifts[i],
            pad=True,
            fill_value=0,
        )
        tr.trim(tr.stats.starttime + 1, tr.stats.endtime - 1, pad=True, fill_value=0)
        tr.stats.starttime = T1
        group_streams += tr

    ST = st[0].copy()
    for tr in st[1:]:
        ST.data = ST.data + tr.data
    ST.data = (ST.data / len(st))
    ST.trim(T1, T2)
    return ST


def make_figure(st, volcano, T0, config, mx_pressure, test=False):

    start = time.time()
    
    ##### get seismic data #####
    t_seis_win = config.seismic_plot_duration if hasattr(config, "seismic_plot_duration") else 3600
    seis = downloading.download_waveforms(volcano["seismic_nslc"], T0 - t_seis_win, T0, fill_value="interpolate")
    ##### get infrasound data #####
    infra_nslc = [tr.id for tr in st]
    t_infra_win = config.infrasound_plot_duration if hasattr(config, "infrasound_plot_duration") else 600
    infra = downloading.download_waveforms(infra_nslc, T0 - t_infra_win, T0, fill_value="interpolate")

    logger.info(f"{time.time() - start:.2f} seconds to grab figure data.")


    #### preprocess data ####
    infra.detrend("demean")
    infra.taper(max_percentage=None, max_length=config.taper_val)
    infra.filter("bandpass", freqmin=config.f1, freqmax=config.f2)
    [tr.decimate(2, no_filter=True) for tr in infra if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in infra if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in infra if tr.stats.sampling_rate != 25]

    seis.detrend("demean")
    [tr.decimate(2, no_filter=True) for tr in seis if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in seis if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in seis if tr.stats.sampling_rate != 25]

    ##### stack infrasound data #####
    logger.info("stacking infrasound data")
    stack = xcorr_align_stream(infra, config)


    ##### set up figure #####
    seis_list = [[f"{tr.stats.station}.{tr.stats.channel}"] for tr in seis]
    axes_list = [["stack_spec"], ["stack_trace"], ["blank"]] + seis_list
    fig, ax = plt.subplot_mosaic(axes_list, figsize=(4.5, 4.5))
    ax["blank"].axis("off")


    ################# plot infrasound #################
    
    ##### plot stack spectrogram #####
    plotting.plot_spectrogram(ax["stack_spec"], stack)
    ax["stack_spec"].set_title(config.alarm_name + " Alarm: " + volcano["volcano"] + " detection!")
    ax["stack_spec"].set_xticks([])

    ##### plot stack trace #####
    ax["stack_trace"].plot(stack.times(), stack.data, color="k", linewidth=0.2)
    ax["stack_trace"].set_yticks([])
    ax["stack_trace"].set_xlim(stack.times()[0], stack.times()[-1])
    stack_st = Stream(stack)
    plotting.format_spec_xaxis(ax["stack_trace"], stack, stack_st, len(stack_st), config, duration=t_infra_win)
    for ax_lab in ["stack_trace", "stack_spec"]:
        ax[ax_lab].set_ylabel(
            stack.stats.station + "\nstack",
            fontsize=5,
            rotation="horizontal",
            multialignment="center",
            horizontalalignment="right",
            verticalalignment="center",
            color="red",
        )

    min_stamp = round(t_infra_win / 60)
    t_stamp = infra[0].stats.starttime.strftime("%Y-%b-%d")
    ax["stack_trace"].set_xlabel(
        f"{min_stamp:.0f} Minute Infrasound Stack\n{t_stamp} UTC,   Peak Pressure: {mx_pressure:.1f} Pa",
        fontsize=6,
    )
    ###################################################


    ################## plot seismic ###################
    for i, tr in enumerate(seis):
        name = f"{tr.stats.station}.{tr.stats.channel}"
        plotting.plot_spectrogram(ax[name], tr)
        plotting.format_spec_xaxis(ax[name], tr, seis, i, config)
        ax[name].set_title("")

    min_stamp = round(t_seis_win / 60)
    ax[name].set_xlabel(
        f"{min_stamp:.0f} Minute Seismic Local Seismic Data",
        fontsize=6,
    )
    ###################################################

    plt.subplots_adjust(left=0.08, right=0.94, top=0.92, bottom=0.1, hspace=0.1)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=250)

    return jpg_file


def create_message(t1, t2, st, volcano, azimuth, d_Azimuth, velocity, mx_pressure):
    # create the subject line
    subject = f"{volcano['volcano']} Airwave Detection"

    # create the text for the message you want to send
    message = f"{messaging.format_timestring(t1, t2)}\n\n"

    message = f"{message}Azimuth: {azimuth:+.1f} degrees\n"
    message = f"{message}d_Azimuth: {d_Azimuth:+.1f} degrees\n"
    message = f"{message}Velocity: {velocity * 1000:.0f} m/s\n"
    message = f"{message}Max Pressure: {mx_pressure:.1f} Pa"

    calc_tt = True
    if "traveltime" in volcano:
        calc_tt = volcano["traveltime"]
    if ("v_lat" in volcano) & calc_tt:
        lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
        lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
        travel_time = UTCDateTime(
            gps2dist_azimuth(lat0, lon0, volcano["v_lat"], volcano["v_lon"])[0] / 333
        )
        if travel_time.hour > 0:
            message = f"{message}\nTravel Time: {travel_time.hour:.0f}h {travel_time.minute:.0f}m {travel_time.second:.0f}s"
        else:
            message = f"{message}\nTravel Time: {travel_time.minute:.0f}m {travel_time.second:.0f}s"

    return subject, message