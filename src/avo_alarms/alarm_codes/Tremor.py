import os
import time
import traceback

import numpy as np
import pandas as pd
from enveloc.core import XCOR
from obspy import UTCDateTime
from obspy.signal.filter import envelope

from avo_alarms.alarm_codes import RSAM
from avo_alarms.utils import downloading, messaging, processing
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    state_message = f"{T0_str} (UTC)"

    if os.getenv("FROMCRON") == "yep":
        time.sleep(getattr(config, "latency") + getattr(config, "taper"))

    tremor_df = pd.read_csv(config.catalog_file, parse_dates=["time"])

    ######### download data #########
    NSLC = pd.DataFrame.from_dict(config.NSLC)
    nslc = NSLC["nslc"].tolist()
    t1 = T0 - 1.5 * config.window_length - config.taper
    t2 = T0 + config.taper
    ## BUG - temporary hack to test on old data
    st = downloading.download_iris_waveforms(nslc, t1, t2, fill_value=0)
    ## BUG end
    st = processing.add_metadata(st)
    
    ##### check for enough data #####
    if qc_checks(st) < config.min_sta:
        state_message = f"{state_message} - Data missing!"
        state = "WARNING"
        # messaging.icinga(config, state, state_message, send=icinga_flag)
        # return

    ######## preprocess data ########
    band_env, high_env, band = preprocess(st, config, t1, t2)
    rsam_st = st.select(id=config.rsam_station)
    rsam_st.filter(
        "bandpass", freqmin=config.f1, freqmax=config.f2, corners=3, zerophase=True
    )
    if rsam_st:
        rsam = np.sqrt(np.mean(np.square(rsam_st[0].data)))
        rsam_test = rsam
    else:
        rsam = 0
        rsam_test = config.rsam_threshold + 1 # test sta missing, ensure alarm can still fire
        subject = f"{config.alarm_name} error"
        message = (
            f"RSAM test station: {config.rsam_station} is missing. Consider replacing"
        )
        messaging.send_alert("Error", subject, message) # warn of missing station
    #################################

    ######### get locations #########
    logger.info("Running enveloc")
    loc = run_enveloc(st, band_env, high_env, config)
    #################################
    

    ##### merge new event with old events #####
    locs_dict = {
        "time": [pd.to_datetime(location.starttime.datetime) for location in loc.events],
        "lat": loc.get_lats(),
        "lon": loc.get_lons(),
    }
    tremor_df = pd.concat([tremor_df, pd.DataFrame(locs_dict)])
    T1 = pd.to_datetime((T0 - config.duration).datetime)
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
    duration_text, recency_text = create_icinga_test(tremor_df, T0, duration, rsam, config)

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
            #### Generate Figure ####
            try:
                logger.info("Making figure")
                filename = RSAM.make_figure(NSLC["nslc"].tolist(), T0, config, test=test_flag)
            except Exception:
                logger.error("Figure failed. Continue...")
                filename = []

            ### Craft message text ####
            subject, message = create_message(
                T0 - config.duration, T0, config.alarm_name, duration_text
            )

            ### Send message ###
            try:
                mm_url = messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
                message = f"{message}\n\n{mm_url}"
            except Exception as e:
                logger.error("problem posting to mattermost")
                logger.error(e)
                logger.error(traceback.format_exc())
                
            messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)
            # delete the file you just sent
            if filename:
                os.remove(filename)
    #################################

    # update catalog file 
    tremor_df.to_csv(config.catalog_file, float_format="%.4f", index=False)

    # update icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)


def test_traveltime(st, config):
    if not config.grid_file.exists():
        logger.warning(f"{config.grid_file} missing")
        return False

    npzfile = np.load(config.grid_file)
    new_grd = config.grid
    if not np.array_equal(new_grd["lats"], npzfile["lats"]):
        logger.warning("Latitude grid nodes do not match. Calculate new travel times")
        return False
    elif not np.array_equal(new_grd["lons"], npzfile["lons"]):
        logger.warning("Longitude grid nodes do not match. Calculate new travel times")
        return False
    elif not np.array_equal(new_grd["deps"], npzfile["deps"]):
        logger.warning("Depth grid nodes do not match. Calculate new travel times")
        return False
    for tr in st:
        if tr.id.replace(".", "_") not in npzfile.keys():
            logger.warning(f"No travel times for {tr.id}! Calculate new travel times")
            return False

    return True


def run_enveloc(st, band_env, high_env, config):

    if test_traveltime(st, config):
        XC = XCOR(
            band_env,
            plot=False,
            bootstrap=config.bstrap,
            bootstrap_prct=config.bstrap_prct,
            Cmin=config.Cmin,
            Cmax=config.Cmax,
            env_hp=high_env,
            grid_size=config.grid,
            tt_file=config.grid_file,
            phase_types=config.phase_list,
        )
    else:
        logger.info("Making new traveltime grid")
        XC = XCOR(
            band_env,
            plot=False,
            bootstrap=config.bstrap,
            bootstrap_prct=config.bstrap_prct,
            Cmin=config.Cmin,
            Cmax=config.Cmax,
            env_hp=high_env,
            grid_size=config.grid,
        )
        XC.save_traveltimes(config.grid_file)
    loc = XC.locate(
        window_length=config.window_length,
        step=config.window_length / 2.0,
        include_partial_windows=False,
    )
    loc = loc.remove(max_scatter=config.max_scatter, inplace=False)
    loc = remove_hp_detects(loc)

    return loc


def create_icinga_test(CAT, T0, duration, rsam, config):

    duration_text = f"Seismicity detected in {round(duration, 1):g} of past {round(config.duration / 60, 1):g} minutes."
    if duration>0:
        last=UTCDateTime(pd.Timestamp(CAT.time.values[-1]).to_pydatetime())+config.window_length
        recency_text = f"Most recent: {round((T0 - last) / 60, 1) + 0.0:g} minutes ago."
    else:
        duration_text = f"No seismicity detected in the past {round(config.duration/60, 1):g} minutes."
        recency_text = ""
    station = config.rsam_station.split('.')[1]
    recency_text = (
        f"{recency_text} {station} RSAM:{rsam:.0f}/{config.rsam_threshold:.0f}"
    )

    return duration_text, recency_text


def create_message(t1, t2, alarm_name, statement):

    subject = f"--- {alarm_name} ---"

    time_str = messaging.format_timestring(t1, t2)
    message = f"{time_str}\n\n{statement}"

    return subject, message


def preprocess(st, config, t1, t2):
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper)

    band = st.copy().filter(
        "bandpass", freqmin=config.f1, freqmax=config.f2, corners=3, zerophase=True
    )
    high = st.copy().filter("highpass", freq=config.highpass, corners=3, zerophase=True)

    band_env = make_env(band.copy(), config, t1, t2)
    high_env = make_env(high, config, t1, t2)

    return band_env, high_env, band


def qc_checks(st):
    for tr in st:
        num_zeros = len(np.where(tr.data == 0)[0])
        if num_zeros / float(tr.stats.npts) > 0.03:
            st.remove(tr)
    lats = []
    for tr in st:
        lats.append(tr.stats.coordinates.latitude)

    return len(np.unique(lats))


def remove_hp_detects(loc):
    A = loc.copy()
    for location in A.events:
        if location.highpass_loc:
            A.events.remove(location)
    return A


def make_env(st, config, t1, t2):
    new_st = st.copy()
    for tr in new_st:
        if tr.stats.sampling_rate > 21:
            tr.resample(25.0)
        if tr.stats.npts % 2 == 1:
            tr.trim(
                starttime=tr.stats.starttime,
                endtime=tr.stats.endtime + 1 / tr.stats.sampling_rate,
                pad=True,
                fill_value=0,
            )
        tr.data = envelope(tr.data)
        tr.resample(5.0)

    new_st.filter("lowpass", freq=config.lowpass, corners=2, zerophase=True)

    new_st.trim(t1 + config.taper, t2 - config.taper + 1, fill_value=0, pad=True)

    return new_st