"""
Detection routines for the Tremor alarm.

Builds the cross-correlation search grid, preprocesses waveform data into
band-passed and high-passed envelopes, runs the ``enveloc`` cross-correlation
locator (reusing or regenerating the travel-time grid as needed), applies QC
and scatter filters to the resulting locations, and formats the Icinga status
text summarizing detected seismicity.
"""

import numpy as np
import pandas as pd
from obspy import UTCDateTime
from obspy.signal.filter import envelope

from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def build_grid(config):
    """Reconstruct the search-grid arrays from scalar bounds and steps.

    Reproduces the arrays the old ``.py`` ``grid`` definition produced via
    ``arange(min, max + 0.001, step)`` for each dimension.

    Parameters
    ----------
    config : object
        Alarm configuration whose ``grid`` attribute holds the ``lon``,
        ``lat``, and ``depth`` min/max/step scalars.

    Returns
    -------
    dict
        Grid axes with keys ``"lons"``, ``"lats"``, and ``"deps"``, each a
        1-D :class:`numpy.ndarray`.
    """
    g = config.grid
    return {
        "lons": np.arange(g["lon_min"], g["lon_max"] + 0.001, g["lon_step"]),
        "lats": np.arange(g["lat_min"], g["lat_max"] + 0.001, g["lat_step"]),
        "deps": np.arange(g["depth_min"], g["depth_max"] + 0.001, g["depth_step"]),
    }


def test_traveltime(st, config, grid):
    """Check whether a cached travel-time grid matches the current setup.

    Compares the stored grid axes against the freshly built ones (with a
    tolerance, since both come from ``np.arange`` and can differ by ~1e-15
    across platforms) and confirms every trace has stored travel times.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose trace ids must be present in the cached grid.
    config : object
        Alarm configuration providing ``grid_file``.
    grid : dict
        Freshly built grid axes (see :func:`build_grid`).

    Returns
    -------
    bool
        True if the cached travel-time grid can be reused, False if it is
        missing, its axes differ, or a trace is absent (travel times must be
        recomputed).
    """
    if not config.grid_file.exists():
        logger.warning(f"{config.grid_file} missing")
        return False

    npzfile = np.load(config.grid_file)
    new_grd = grid
    # Compare grid axes with allclose (not array_equal): both the stored grid and
    # the freshly-built one come from np.arange, which can differ by ~1e-15 across
    # numpy/platform versions. An exact comparison would treat those identical
    # grids as mismatched and needlessly recompute the whole travel-time grid on
    # every run. Genuine grid-definition changes differ far above this tolerance.
    def _axes_differ(a, b):
        """Return True if two grid axes differ in shape or beyond tolerance."""
        return a.shape != b.shape or not np.allclose(a, b)

    if _axes_differ(new_grd["lats"], npzfile["lats"]):
        logger.warning("Latitude grid nodes do not match. Calculate new travel times")
        return False
    elif _axes_differ(new_grd["lons"], npzfile["lons"]):
        logger.warning("Longitude grid nodes do not match. Calculate new travel times")
        return False
    elif _axes_differ(new_grd["deps"], npzfile["deps"]):
        logger.warning("Depth grid nodes do not match. Calculate new travel times")
        return False
    for tr in st:
        if tr.id.replace(".", "_") not in npzfile:
            logger.warning(f"No travel times for {tr.id}! Calculate new travel times")
            return False

    return True


def run_enveloc(st, band_env, high_env, config):
    """Locate tremor via envelope cross-correlation.

    Builds (or reuses) the travel-time grid, runs the ``enveloc`` cross-
    correlation locator over sliding windows, then removes high-scatter and
    high-pass-only detections.

    Parameters
    ----------
    st : obspy.Stream
        Raw stream, used to decide whether the cached travel-time grid applies.
    band_env : obspy.Stream
        Band-passed envelope stream the locator correlates.
    high_env : obspy.Stream
        High-passed envelope stream used as the high-pass check.
    config : object
        Alarm configuration (bootstrap, Cmin/Cmax, phase list, window length,
        scatter, and grid settings).

    Returns
    -------
    enveloc location object
        The located events with high-scatter and high-pass-only detections
        removed.
    """
    from enveloc.core import XCOR

    grid = build_grid(config)
    # Use config.grid_file directly (matches how test_traveltime locates it).
    grid_file = config.grid_file
    if test_traveltime(st, config, grid):
        XC = XCOR(
            band_env,
            plot=False,
            bootstrap=config.bstrap,
            bootstrap_prct=config.bstrap_prct,
            Cmin=config.Cmin,
            Cmax=config.Cmax,
            env_hp=high_env,
            grid_size=grid,
            tt_file=grid_file,
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
            grid_size=grid,
        )
        XC.save_traveltimes(grid_file)
    loc = XC.locate(
        window_length=config.window_length,
        step=config.window_length / 2.0,
        include_partial_windows=False,
    )
    loc = loc.remove(max_scatter=config.max_scatter, inplace=False)
    loc = remove_hp_detects(loc)

    return loc


def remove_hp_detects(loc):
    """Drop high-pass-only detections from a location set.

    Parameters
    ----------
    loc : enveloc location object
        Located events, each exposing a ``highpass_loc`` flag.

    Returns
    -------
    enveloc location object
        A copy with the high-pass-flagged events removed.
    """
    A = loc.copy()
    for location in A.events:
        if location.highpass_loc:
            A.events.remove(location)
    return A


def preprocess(st, config, t1, t2):
    """Prepare waveform data for the envelope locator.

    Detrends and tapers the stream, builds band-passed and high-passed copies,
    trims/pads them to the window, and converts them to resampled, low-passed
    envelopes.

    Parameters
    ----------
    st : obspy.Stream
        Raw input stream.
    config : object
        Alarm configuration (``taper``, filter corners ``f1``/``f2``,
        ``highpass``, ``lowpass``).
    t1 : obspy.UTCDateTime
        Start time of the processing window.
    t2 : obspy.UTCDateTime
        End time of the processing window.

    Returns
    -------
    band_env : obspy.Stream
        Band-passed envelope stream.
    high_env : obspy.Stream
        High-passed envelope stream.
    band : obspy.Stream
        Band-passed (non-envelope) stream, used for RSAM and QC.
    """
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper)

    band = st.copy().filter(
        "bandpass", freqmin=config.f1, freqmax=config.f2, corners=2, zerophase=True
    )
    high = st.copy().filter("highpass", freq=config.highpass, corners=2, zerophase=True)
    
    band.merge(fill_value=0)
    band.trim(t1, t2, pad=True, fill_value=0)
    
    high.merge(fill_value=0)
    high.trim(t1, t2, pad=True, fill_value=0)

    band_env = make_env(band.copy(), config, t1, t2)
    high_env = make_env(high, config, t1, t2)

    return band_env, high_env, band


def qc_checks(st):
    """Drop gappy traces and count distinct station latitudes.

    Removes any trace that is more than 3% zeros (a proxy for missing data),
    then counts the unique station latitudes remaining, used as the station
    count for the minimum-station gate.

    Parameters
    ----------
    st : obspy.Stream
        Stream to QC in place; traces carry ``stats.coordinates.latitude``.

    Returns
    -------
    int
        Number of unique station latitudes among the surviving traces.
    """
    for tr in st:
        num_zeros = len(np.where(tr.data == 0)[0])
        if num_zeros / float(tr.stats.npts) > 0.03:
            st.remove(tr)
    lats = []
    for tr in st:
        lats.append(tr.stats.coordinates.latitude)

    return len(np.unique(lats))


def make_env(st, config, t1, t2):
    """Convert a stream into a resampled, low-passed envelope.

    Resamples each trace to 25 Hz (if above 21 Hz), pads to even length,
    computes the analytic-signal envelope, resamples to 5 Hz, applies a
    low-pass filter, and trims to the taper-free interior of the window.

    Parameters
    ----------
    st : obspy.Stream
        Input stream (modified in place).
    config : object
        Alarm configuration (``lowpass`` corner, ``taper``).
    t1 : obspy.UTCDateTime
        Window start time.
    t2 : obspy.UTCDateTime
        Window end time.

    Returns
    -------
    obspy.Stream
        The envelope stream, trimmed to ``[t1 + taper, t2 - taper + 1]``.
    """
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


def create_icinga_test(CAT, T0, duration, rsam, config):
    """Build the Icinga status text summarizing recent seismicity.

    Parameters
    ----------
    CAT : pandas.DataFrame
        Catalog of recent tremor/swarm events with a ``time`` column.
    T0 : obspy.UTCDateTime
        End time of the processing window.
    duration : float
        Total detected seismicity duration in minutes over the lookback window.
    rsam : float
        RSAM value at the configured test station.
    config : object
        Alarm configuration (``lookback_window``, ``window_length``,
        ``rsam_station``, ``rsam_threshold``).

    Returns
    -------
    duration_text : str
        Sentence describing how much seismicity was detected.
    recency_text : str
        Sentence giving the most-recent detection time and the station RSAM
        value against its threshold.
    """
    duration_text = f"Seismicity detected in {round(duration, 1):g} of past {config.lookback_window:g} minutes."
    if duration > 0:
        last = UTCDateTime(pd.Timestamp(CAT.time.values[-1]).to_pydatetime()) + config.window_length
        recency_text = f"Most recent: {round((T0 - last) / 60, 1) + 0.0:g} minutes ago."
    else:
        duration_text = f"No seismicity detected in the past {config.lookback_window:g} minutes."
        recency_text = ""
    station = config.rsam_station.split('.')[1]
    recency_text = (
        f"{recency_text} {station} RSAM:{rsam:.0f}/{config.rsam_threshold:.0f}"
    )

    return duration_text, recency_text
