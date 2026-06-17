from itertools import combinations

import numpy as np
from obspy import Stream
from obspy.geodetics.base import gps2dist_azimuth
from obspy.signal.cross_correlation import correlate, xcorr_max

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def get_target_backazimuth(st, config):
    lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
    lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
    for target in config.targets:
        if "back_azimuth" not in target:
            tmp = gps2dist_azimuth(lat0, lon0, target["lat"], target["lon"])
            target["back_azimuth"] = tmp[1]
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
            shift = int(config.cc_shift_length * st[0].stats.sampling_rate)
            cc_vector = correlate(st[ii].data, st[jj].data, shift)
            index, value = xcorr_max(cc_vector)
            #### if best xcorr value is negative, find the best positive one ####
            if value < 0:
                index = cc_vector.argmax() - shift
                value = cc_vector.max()
            dt = index / st[0].stats.sampling_rate
            #### check that the best lag is at least the vmin value
            #### and check for minimum cross correlation value
            all_vmin = np.array([v["vmin"] for v in config.targets]).min()
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


def inversion(cmbm2n, cmbm2, intsd, ints_az, lags_inds1, lags_inds2, lags, mpk):
    # for jj in range(counter):
    jj = 0
    # the size of the dt and Dm3
    dt = np.zeros(cmbm2n[jj])
    Dm3 = np.zeros((cmbm2n[jj], 2))

    # initialize interstation distance and azimuth vectors
    ds = np.array([])
    az = np.array([])

    # grab interstation distance and azimuth for all pairs in this tuple
    for num, kk in enumerate(cmbm2[jj, range(0, mpk - 1)]):
        for ii in cmbm2[jj, range(num + 1, mpk)]:
            ds = np.append(ds, intsd[kk, ii])
            az = np.append(az, ints_az[kk, ii])

    # some counters to find if there is a match in the trgs vector
    mtrxc = 0
    dacnt = 0

    # all 5 may not exist
    for kk in range(0, mpk - 1):
        for ii in range(kk + 1, mpk):
            tmp = np.array([lags_inds1, lags_inds2]).T - np.repeat(np.array([cmbm2[jj, kk], cmbm2[jj, ii]], ndmin=2), len(lags_inds1), 0)
            tmp = np.sum(np.abs(tmp), 1)
            mmin = tmp.min()
            mloc = tmp.argmin()
            if mmin == 0:
                dt[mtrxc] = lags[mloc]
                Dm3[mtrxc, :] = [ds[dacnt] * np.cos(az[dacnt] * (np.pi / 180.0)), ds[dacnt] * np.sin(az[dacnt] * (np.pi / 180.0))]
                mtrxc = mtrxc + 1
            dacnt = dacnt + 1
    Dm3 = Dm3 / 1000.0  # convert to kilometers

    # generalized inverse of slowness matrix
    Gmi = np.linalg.inv(np.matmul(Dm3.T, Dm3))
    # slowness - least squares
    sv = np.matmul(np.matmul(Gmi, Dm3.T), dt.T)
    # velocity from slowness
    velocity = 1 / np.sqrt(np.square(sv[0]) + np.square(sv[1]))
    # cosine and sine for backazimuth
    caz3 = velocity * sv[0]
    saz3 = velocity * sv[1]
    # 180 degree resolved backazimuth to source
    azimuth = np.arctan2(saz3, caz3) * (180 / np.pi)
    if azimuth < 0:
        azimuth = azimuth + 360
    # rms
    rms = np.sqrt(np.mean(np.square(np.matmul(Dm3, sv) - dt.T)))

    return velocity, azimuth, rms


def xcorr_align_stream(st, config):

    shift_len = int(config.cc_shift_length * st[0].stats.sampling_rate)
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
