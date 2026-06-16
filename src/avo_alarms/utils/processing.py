import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import UTCDateTime, read_inventory, Catalog
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.geodetics import gps2dist_azimuth
from obspy.core.event import Event
from pandas.errors import EmptyDataError

from avo_alarms.utils.setup_utils import get_logger, load_volcano_list
from avo_alarms.utils.downloading import IRIS_client

logger = get_logger(__name__)


def compare_to_old_events(df, event_file, default_cols, unique_id_col="id"):

    if not event_file.exists():
        logger.warning(f"No event file found at {event_file}. Creating new file.")
        blank_df = pd.DataFrame(columns=default_cols)
        blank_df.to_csv(event_file, index=False)
        logger.warning(f"Created {event_file.absolute()} with headers: {default_cols}")

    try:
        old_events_df = pd.read_csv(event_file)
    except EmptyDataError:
        logger.warning(f"Empty file found at {event_file}. Assigning headers with default columns.")
        old_events_df = pd.DataFrame(columns=default_cols)

    new_events_df = df[~df[unique_id_col].isin(old_events_df[unique_id_col])]

    if len(new_events_df) > 0:
        logger.info(f"New events since last check:\n{new_events_df}")
    else:
        logger.info("No new events since last check.")

    logger.info(f"{len(old_events_df)} old and {len(new_events_df)} new events")

    return new_events_df, df


def write_to_csv(df, config, columns):

    logger.info(f"Writing {len(df)} events to {config.outfile}")
    if len(df) == 0:
        df = pd.DataFrame(columns=columns)
        
    df.to_csv(config.outfile, columns=columns, index=False, date_format='%Y-%m-%d %H:%M:%S.%f')

    return


def find_nearest_volcano(df, lon_col="longitude", lat_col="latitude", volc_df=None):

    if volc_df is None:
        volc_df = load_volcano_list()
    V_DIST = []
    V_NAME = []

    for _, row in df.iterrows():
        volc_df = volcano_distance(row[lon_col], row[lat_col], volc_df)
        V_DIST.append(volc_df.iloc[0].distance)
        V_NAME.append(volc_df.iloc[0].Name)

    df["v_distance"] = V_DIST
    df["v_name"] = V_NAME

    return df


def volcano_distance(lon0, lat0, volcs):
    """_summary_

    Parameters
    ----------
    lon0 : _type_
        _description_
    lat0 : _type_
        _description_
    volcs : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """

    DIST = np.array([])
    for lat, lon in zip(volcs.Latitude.values, volcs.Longitude.values):
        dist, azimuth, az2 = gps2dist_azimuth(lat, lon, lat0, lon0)
        DIST = np.append(DIST, dist / 1000.0)
    volcs.loc[:, "distance"] = DIST

    volcs = volcs.sort_values("distance")

    return volcs


def catalog_to_dataframe(CAT, VOLCS):

    LATS = []
    LONS = []
    DEPS = []
    MAGS = []
    TIME = []
    ID = []
    RMS = []
    AZ_GAP = []
    V_DIST = []

    for eq in CAT:
        LATS.append(eq.preferred_origin().latitude)
        LONS.append(eq.preferred_origin().longitude)
        DEPS.append(eq.preferred_origin().depth / 1000)
        TIME.append(eq.preferred_origin().time.datetime)
        try:
            RMS.append(eq.preferred_origin().quality.standard_error)
        except Exception:
            RMS.append(1e2)
        try:
            AZ_GAP.append(eq.preferred_origin().quality.azimuthal_gap)
        except Exception:
            AZ_GAP.append(360)
        if eq.preferred_magnitude():
            MAGS.append(eq.preferred_magnitude().mag)
        else:
            MAGS.append(np.nan)
        evid = eq.resource_id.id
        ID.append(evid)

        volcs = volcano_distance(
            eq.preferred_origin().longitude, eq.preferred_origin().latitude, VOLCS
        )
        volcs = volcs.sort_values("distance")
        V_DIST.append(volcs.iloc[0].distance)

    cat_df = pd.DataFrame(
        {
            "Time": TIME,
            "Latitude": LATS,
            "Longitude": LONS,
            "Depth": DEPS,
            "Magnitude": MAGS,
            "ID": ID,
            "V_DIST": V_DIST,
        }
    )
    cat_df["Time"] = pd.to_datetime(cat_df["Time"])

    return cat_df


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

    client = IRIS_client()

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


def Dr_to_RSAM(config, DR, volcano_name, base=25):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    DR : _type_
        _description_
    volcano_name : _type_
        _description_
    base : int, optional
        _description_, by default 25
    """

    client = FDSN_Client("IRIS")

    VELOCITY = 1.5  # km/s
    FREQ = 2  # dominant frequency (Hz)
    Q = 200  # quality factor

    T0 = UTCDateTime.utcnow()
    VOLCS = load_volcano_list()
    volcs = VOLCS[VOLCS["Name"] == volcano_name].copy()
    NSLC = pd.DataFrame.from_dict(config.NSLC)

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

        logger.info(f"{nslc}: {lvl:g}")

    return


def check_inventory(tr, inv):
    """
    Check if a trace exists in the inventory.

    Args:
        tr (Trace): ObsPy Trace object.
        inv (Inventory): ObsPy Inventory object.

    Returns:
        bool: True if the trace exists in the inventory, False otherwise.
    """
    
    inv_test = inv.select(
        network=tr.stats.network,
        station=tr.stats.station,
        location=tr.stats.location,
        channel=tr.stats.channel,
        starttime=tr.stats.starttime,
        endtime=tr.stats.starttime,
    )
    value = True if len(inv_test) > 0 else False
    return value


def add_metadata(st):
    """
    Add metadata to traces in a stream.

    Args:
        st (Stream): ObsPy Stream object.
        config (dict): Configuration dictionary.

    Returns:
        Stream: Stream with updated metadata.
    """

    xml_file = Path(os.getenv("STATION_XML", "blank"))
    if not xml_file.exists():
        logger.error("Station XML file missing")
        return

    inventory = read_inventory(xml_file)

    for tr in st:
        logger.info(f"Getting metadata for {tr.id}")

        # if check_inventory(tr, inventory):
        inv = inventory.select(
            network=tr.stats.network,
            station=tr.stats.station,
            location=tr.stats.location,
            channel=tr.stats.channel,
            starttime=tr.stats.starttime,
            endtime=tr.stats.endtime,
        )
        tr.stats.coordinates = inv.get_coordinates(tr.id, tr.stats.starttime)
        tr.inventory = inv

    return st