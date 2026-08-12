import numpy as np
import pandas as pd
from matplotlib import dates
from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from lts_array import ltsva
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def QC_data(st, config):

    #### Check for enough data ####
    check_st = st.copy()
    skip_chans = []
    good_data = True
    for tr in check_st:
        if np.sum(np.abs(tr.data)) == 0: # pragma: no cover
            # Check for blank traces
            skip_chans.append(tr.id)
            check_st.remove(tr)
    if len(check_st) < config.min_chan: # pragma: no cover
        logger.warning("Too many blank traces. Skipping.")
        good_data = False
        return good_data, skip_chans
    ########################

    #### Check for gappy data ####
    for tr in check_st:
        gap_fraction = np.count_nonzero(tr.data == 0) / tr.stats.npts
        if gap_fraction > config.max_gap_fraction: # pragma: no cover
            # Gap exceeds tolerance. Flag channel for exclusion.
            logger.warning(
                f"{tr.id}: {gap_fraction:.1%} gap exceeds MAX_GAP_FRACTION ({config.max_gap_fraction:.1%}). Skipping channel."
            )
            skip_chans.append(tr.id)
            check_st.remove(tr)
    if len(check_st) < config.min_chan: # pragma: no cover
        logger.warning("Too gappy. Skipping.")
        good_data = False

    return good_data, skip_chans


def get_target_backazimuth(st, config):
    lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
    lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
    for target in config.targets:
        if "back_azimuth" not in target:
            tmp = gps2dist_azimuth(lat0, lon0, target["lat"], target["lon"])
            target["back_azimuth"] = tmp[1]
    return config


def do_LTS(st, config, skip_chans=[]):

    overlap_fraction = config.lts_overlap / config.lts_window_length
    ALPHA = config.lts_alpha if len(st) > 3 else 1.0
    if len(st) - len(skip_chans) < 4:
        logger.warning("3 or fewer stations remaining after QC. Setting LTS_ALPHA to 1.0")
        ALPHA = 1.0
    skip_inds = [i for i, tr in enumerate(st) if tr.id in skip_chans]
    lat_list = [tr.stats.coordinates.latitude for tr in st]
    lon_list = [tr.stats.coordinates.longitude for tr in st]
    logger.info(f"Performing LTS analysis with N={config.lts_n_samples} samples...")
    velocity, azimuth, t, mccm, lts_dict, sigma_tau, Vel_err, Baz_err = ltsva(
        st.copy(), lat_list, lon_list, config.lts_window_length, overlap_fraction, alpha=ALPHA, n_samples=config.lts_n_samples, remove_elements=skip_inds
    )
    logger.info("Done calculating LTS")

    df = pd.DataFrame({
        "Time": t,
        "Azimuth": azimuth,
        "Velocity": 1000 * velocity, # Convert velocity to m/s
        "MCCM": mccm,
        "Pressure": get_pressures(st, t, config),
        "Sigma_tau": sigma_tau,
        "Vel_err": 1000 * Vel_err, # Convert to m/s
        "Baz_err": Baz_err
    })

    return df, lts_dict


def get_pressures(st, t, config):
    """Extract pressure data from the seismic stream.

    Args:
        st (obspy.Stream): Stream containing seismic traces.
        t (np.ndarray): Array of time values (matplotlib dates) from ltsva.
        array_params (dict): Array parameters including window length.

    Returns:
        np.ndarray: Array of pressure values.
    """

    pressure = []
    for ti in t:
        t1 = utc(dates.num2date(ti)) - config.lts_window_length / 2
        t2 = t1 + config.lts_window_length
        st_win = st.slice(t1, t2)
        mx_pressures = np.array([np.max(np.abs(tr_win.data)) for tr_win in st_win])
        pressure.append(np.median(mx_pressures))
    pressure = np.array(pressure)
    return pressure


def filter_lts_results(DF, target):
    # Cross-correlation
    df = DF.copy()
    df = df[df["MCCM"] > target["cmin"]]
    
    # Pressure
    df = df[df["Pressure"] > target["min_pa"]]
    
    # Velocity
    df = df[df["Velocity"]/1000 > target["vmin"]]
    df = df[df["Velocity"]/1000 < target["vmax"]]
    
    # Azimuth
    df = df[df["Azimuth"] > target["back_azimuth"] - target["az_tolerance"]]
    df = df[df["Azimuth"] < target["back_azimuth"] + target["az_tolerance"]]
    
    return df
