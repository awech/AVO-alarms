from pathlib import Path

import numpy as np
import pandas as pd
from enveloc.core import XCOR
from obspy import UTCDateTime
from obspy.signal.filter import envelope

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def build_grid(config):
    """Reconstruct the search-grid arrays from the scalar bounds/steps in
    ``config.grid``. Reproduces the arrays the old ``.py`` ``grid`` definition
    produced via ``arange(min, max + 0.001, step)`` for each dimension."""
    g = config.grid
    return {
        "lons": np.arange(g["lon_min"], g["lon_max"] + 0.001, g["lon_step"]),
        "lats": np.arange(g["lat_min"], g["lat_max"] + 0.001, g["lat_step"]),
        "deps": np.arange(g["depth_min"], g["depth_max"] + 0.001, g["depth_step"]),
    }


def test_traveltime(st, config, grid):
    if not config.grid_file.exists():
        logger.warning(f"{config.grid_file} missing")
        return False

    npzfile = np.load(config.grid_file)
    new_grd = grid
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

    grid = build_grid(config)
    grid_file = Path("tmp_files") / config.grid_file
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
    A = loc.copy()
    for location in A.events:
        if location.highpass_loc:
            A.events.remove(location)
    return A


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


def create_icinga_test(CAT, T0, duration, rsam, config):

    duration_text = f"Seismicity detected in {round(duration, 1):g} of past {round(config.duration / 60, 1):g} minutes."
    if duration > 0:
        last = UTCDateTime(pd.Timestamp(CAT.time.values[-1]).to_pydatetime()) + config.window_length
        recency_text = f"Most recent: {round((T0 - last) / 60, 1) + 0.0:g} minutes ago."
    else:
        duration_text = f"No seismicity detected in the past {round(config.duration/60, 1):g} minutes."
        recency_text = ""
    station = config.rsam_station.split('.')[1]
    recency_text = (
        f"{recency_text} {station} RSAM:{rsam:.0f}/{config.rsam_threshold:.0f}"
    )

    return duration_text, recency_text
