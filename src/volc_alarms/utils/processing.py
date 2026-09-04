import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Catalog, UTCDateTime, read_inventory
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.core.event import Event
from obspy.geodetics import gps2dist_azimuth

from volc_alarms.utils.downloading import Earthscope_client
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)


def find_nearest_volcano(df, lon_col="longitude", lat_col="latitude", filter_col=None, volc_df=None):

    if volc_df is None:
        volc_df = load_volcano_list()
    V_DIST = []
    V_NAME = []
    
    if filter_col is not None and filter_col in volc_df.columns:
        volc_df = volc_df[volc_df[filter_col] != "N"]

    for _, row in df.iterrows():
        volc_df = volcano_distance(row[lon_col], row[lat_col], volc_df)
        nearest = volc_df.loc[volc_df["distance"].idxmin()]
        V_DIST.append(nearest.distance)
        V_NAME.append(nearest.Name)

    df["v_distance"] = V_DIST
    df["v_name"] = V_NAME

    return df


def volcano_distance(lon0, lat0, volcs, filter_col=None):
    """Compute distance from a point to each volcano and sort by distance.

    Parameters
    ----------
    lon0 : float
        Longitude of the reference point (degrees).
    lat0 : float
        Latitude of the reference point (degrees).
    volcs : pandas.DataFrame
        Volcano table with ``Latitude`` and ``Longitude`` columns.
    filter_col : str, optional
        Name of a per-alarm opt-in column (e.g. ``"PIREP"``, ``"SO2"``). When
        provided and present in ``volcs``, rows whose value in that column is
        ``"N"`` are dropped before distances are computed. Ignored if the
        column is absent.

    Returns
    -------
    pandas.DataFrame
        Copy of ``volcs`` with an added ``distance`` column (km), sorted by
        ascending distance.
    """

    if filter_col is not None and filter_col in volcs.columns:
        volcs = volcs[volcs[filter_col] != "N"]

    DIST = np.array([])
    for lat, lon in zip(volcs.Latitude.values, volcs.Longitude.values):
        dist, azimuth, az2 = gps2dist_azimuth(lat, lon, lat0, lon0)
        DIST = np.append(DIST, dist / 1000.0)
    volcs.loc[:, "distance"] = DIST

    volcs = volcs.sort_values("distance")

    return volcs


def addPhaseHint(cat):
    for eq in cat: # Loop over catalog
        for pick in eq.picks: # Loop over picks
            nowPickID = pick.resource_id # Go get phase hint
            for arrival in eq.preferred_origin().arrivals:
                nowArrID = arrival.pick_id
                if nowPickID == nowArrID:
                    pick.phase_hint = arrival.phase
    return cat


def eq_picks_to_dataframe(cat):

    client = Earthscope_client()

    NS = []
    NSLC = []
    LATS = []
    LONS = []
    DIST = []

    if isinstance(cat, Event):
        catalog = Catalog([cat])
    else:
        catalog = cat

    for eq in catalog:
        for p in eq.picks:
            wid = p.waveform_id
            net, sta, loc, chan = wid.id.split(".")
            ns = ".".join([net, sta])
            if ns not in NS:
                logger.info(f"Getting lat/lon info for {wid.id}")
                inventory = client.get_stations(
                    network=net, station=sta, location=loc, channel=chan
                )

                sta_lat = inventory[0][0].latitude
                sta_lon = inventory[0][0].longitude
                dist = (
                    gps2dist_azimuth(
                        eq.preferred_origin().latitude,
                        eq.preferred_origin().longitude,
                        sta_lat,
                        sta_lon,
                    )[0]
                    / 1000.0
                )

                NS.append(ns)
                NSLC.append(wid.id)
                LATS.append(sta_lat)
                LONS.append(sta_lon)
                DIST.append(dist)

    STAS = pd.DataFrame(
        {
            "NS": NS,
            "NSLC": NSLC,
            "Latitude": LATS,
            "Longitude": LONS,
            "Distance": DIST,
        }
    )

    if isinstance(cat, Event):
        STAS["P"] = None
        STAS["S"] = None
        for p in eq.picks:
            ns = ".".join(p.waveform_id.id.split(".")[:2])
            STAS.loc[STAS.NS == ns, p.phase_hint] = p.time

    STAS = STAS.sort_values("Distance")

    return STAS


def Dr_to_RSAM(DR, config=None, nslc_list=None, volcano=None, base=25):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    DR : _type_
        _description_
    volcano : str, optional
        _description_
    base : int, optional
        _description_, by default 25
    """

    client = FDSN_Client("earthscope")

    VELOCITY = 1.5  # km/s
    FREQ = 2  # dominant frequency (Hz)
    Q = 200  # quality factor

    T0 = UTCDateTime.utcnow()
    VOLCS = load_volcano_list()
    if not volcano:
        try:
            volcano = config.volcano_name
        except AttributeError:
            logger.error("Volcano name not specified")
            return

    volcs = VOLCS[VOLCS["Name"] == volcano].copy()

    if config:
        # Reconstruct the ordered station list with the arrestor station last
        stations = (
            list(config.rsam_stations)
            + [config.arrestor]
        )
    elif nslc_list:
        if isinstance(nslc_list, str):
            nslc_list = [nslc_list]
        stations = {"nslc": nslc_list}
    else:
        logger.error("No config or station list provided")
        return
    
    NSLC = pd.DataFrame.from_dict(stations)
    for nslc in NSLC.nslc:
        net, sta, loc, chan = nslc.split(".")
        inventory = client.get_stations(
            network=net,
            station=sta,
            channel=chan,
            location=loc,
            starttime=T0,
            endtime=T0,
            level="response",
        )

        coords = inventory.get_coordinates(nslc)
        gain = inventory.get_response(
            nslc, T0
        ).instrument_sensitivity.value  # counts/m/s

        volcs = volcano_distance(coords["longitude"], coords["latitude"], volcs)
        R = volcs.iloc[0].distance

        # distance, velocity and wavelength in cm
        r = R * 1000 * 100
        velocity = VELOCITY * 1000 * 100
        wavelength = velocity / FREQ

        #### account for attenuation ####
        numerator = -np.pi * FREQ * r
        denominator = Q * velocity
        atten_factor = np.exp(numerator / denominator)

        rmssta = DR / np.sqrt(r * wavelength)  # rms in cm
        rmssta_v = (
            rmssta * 2 * np.pi * FREQ
        ) / 100  # convert to velocity and change from cm to m (for the gain)
        lvl = (
            rmssta_v * gain * atten_factor
        )  # use gain to turn m/s to counts, and apply attenuation

        lvl = base * np.round(lvl / base)

        print(f"{nslc}: {lvl:g}")
        logger.info(f"{nslc}: {lvl:g}")

    return


def add_metadata(st):
    """
    Add metadata to traces in a stream.

    Args:
        st (Stream): ObsPy Stream object.
        config (dict): Configuration dictionary.

    Returns:
        Stream: Stream with updated metadata.
    """

    xml_file = Path(os.environ["STATION_XML"])
    if not xml_file.exists():
        logger.error("Station XML file missing")
        return

    inventory = read_inventory(xml_file)

    for tr in st:
        logger.info(f"Getting metadata for {tr.id}")

        inv = inventory.select(
            network=tr.stats.network,
            station=tr.stats.station,
            location=tr.stats.location,
            channel=tr.stats.channel,
            starttime=tr.stats.starttime,
            endtime=tr.stats.endtime,
        )
        tr.stats.coordinates = inv.get_coordinates(tr.id, tr.stats.starttime)
        tr.stats.inventory = inv

    return st


def preprocess_stream(st, t1, t2, config):
    st.detrend("demean")
    st.taper(max_percentage=None, max_length=config.taper)
    st.filter("bandpass", freqmin=config.f1, freqmax=config.f2, corners=2, zerophase=True)
    st.merge(fill_value=0)
    
    gaps = st.get_gaps()
    if gaps:
        logger.warning(f"Gappy data: {len(gaps)} gap(s)/overlap(s)")
        for net, sta, loc, chan, t_last, t_next, delta, samples in gaps:
            logger.warning(
                f"{net}.{sta}.{loc}.{chan}: {t_last} -> {t_next} "
                f"(delta={delta:.3f}s, samples={samples})"
            )
        logger.warning("Attempting to merge (fill_value=0)")
        st.merge(fill_value=0)
    
    st.trim(t1, t2, pad=True, fill_value=0)
    return st


def remove_gain(st):
    """
    Remove instrument gain/sensitivity from traces in a stream.

    Note: inventory is stashed on ``tr.stats.inventory`` (not a bare
    ``tr.inventory`` attribute) since ``Trace.stats`` is deep-copied by
    ``Stream.merge()`` and ``Trace.copy()``, while arbitrary attributes
    set directly on a ``Trace`` object are not preserved by either.

    Args:
        st (Stream): ObsPy Stream object.

    Returns:
        Stream: Stream with gain removed.
    """
    for tr in st:
        if "inventory" in tr.stats and tr.stats.inventory is not None:
            tr.remove_sensitivity(tr.stats.inventory)
        else: # pragma: no cover
            logger.warning(f"{tr.id}: no inventory attached. Skipping gain removal.")
    return st