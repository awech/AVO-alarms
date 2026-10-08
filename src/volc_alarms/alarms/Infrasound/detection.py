"""
Detection routines for the Infrasound alarm.

Provides the quality-control, array-geometry, and least-trimmed-squares (LTS)
processing steps that turn a conditioned infrasound stream into a table of
per-window back-azimuth, trace velocity, cross-correlation (MCCM), and peak
pressure estimates, plus the per-target filtering that identifies airwave
detections.
"""

import numpy as np
import pandas as pd
from matplotlib import dates
from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from volc_alarms._vendor.lts_array import ltsva
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def QC_data(st, config):
    """Quality-control an infrasound stream before array processing.

    Drops blank (all-zero) traces and traces whose gap fraction exceeds
    ``config.max_gap_fraction``, and reports whether enough channels remain
    (at least ``config.min_chan``).

    Parameters
    ----------
    st : obspy.Stream
        Conditioned infrasound stream to check.
    config : object
        Configuration exposing ``min_chan`` and ``max_gap_fraction``.

    Returns
    -------
    good_data : bool
        True if enough usable channels remain, False otherwise.
    skip_chans : list of str
        Trace ids that were flagged for exclusion (blank or too gappy).
    """

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
    """Compute and cache each target's back-azimuth from the array center.

    For every target lacking a ``back_azimuth``, computes it from the mean
    array coordinates to the target's ``lat``/``lon`` and stores it on the
    target dict.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose traces carry ``stats.coordinates`` (latitude/longitude).
    config : object
        Configuration exposing ``targets`` as a list of dicts with
        ``lat``/``lon``.

    Returns
    -------
    object
        The same ``config`` with each target's ``back_azimuth`` populated.
    """

    lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
    lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
    for target in config.targets:
        if "back_azimuth" not in target:
            tmp = gps2dist_azimuth(lat0, lon0, target["lat"], target["lon"])
            target["back_azimuth"] = tmp[1]
    return config


def do_LTS(st, config, skip_chans=None):
    """Run least-trimmed-squares array processing on an infrasound stream.

    Calls :func:`volc_alarms._vendor.lts_array.ltsva` with the configured window length, overlap,
    alpha, and sample count, then assembles the per-window results into a
    DataFrame. ``alpha`` is forced to 1.0 when three or fewer channels remain
    after excluding ``skip_chans``.

    Parameters
    ----------
    st : obspy.Stream
        Conditioned stream whose traces carry ``stats.coordinates``.
    config : object
        Configuration exposing ``lts_overlap``, ``lts_window_length``,
        ``lts_alpha``, and ``lts_n_samples``.
    skip_chans : list of str or None, optional
        Trace ids to exclude from the inversion. ``None`` (the default) is
        treated as an empty list.

    Returns
    -------
    df : pandas.DataFrame
        Per-window results with columns ``Time``, ``Azimuth``, ``Velocity``
        (m/s), ``MCCM``, ``Pressure``, ``Sigma_tau``, ``Vel_err`` (m/s), and
        ``Baz_err``.
    lts_dict : dict
        The raw LTS diagnostic dictionary returned by ``ltsva``.
    """

    if skip_chans is None:
        skip_chans = []
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
    """Compute the median peak pressure in each LTS window.

    For each time in ``t``, slices the stream to a window of width
    ``config.lts_window_length`` centered on that time, takes each trace's
    peak absolute amplitude, and returns the median across traces.

    Parameters
    ----------
    st : obspy.Stream
        Stream containing the infrasound traces.
    t : numpy.ndarray
        Window center times as matplotlib date numbers, from ``ltsva``.
    config : object
        Configuration exposing ``lts_window_length`` (seconds).

    Returns
    -------
    numpy.ndarray
        Median peak pressure for each window, in the same order as ``t``.
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
    """Filter LTS windows to those consistent with a target airwave.

    Keeps only windows whose cross-correlation, pressure, trace velocity, and
    back-azimuth all fall within the target's acceptance criteria.

    Parameters
    ----------
    DF : pandas.DataFrame
        Per-window LTS results, as produced by :func:`do_LTS`.
    target : dict
        Target acceptance criteria: ``cmin``, ``min_pa``, ``vmin``, ``vmax``,
        ``back_azimuth``, and ``az_tolerance``.

    Returns
    -------
    pandas.DataFrame
        The subset of ``DF`` whose windows satisfy every target criterion.
    """

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
