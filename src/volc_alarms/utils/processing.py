"""
Seismic processing and geospatial helpers for the alarms package.

Groups the routines that transform waveform and catalog data on the way to a
detection or message: associating earthquakes with the nearest volcano,
computing station-to-volcano distances, flattening obspy catalog picks into
DataFrames, converting between reduced displacement and RSAM levels, and
standard waveform conditioning (metadata attachment, gain removal, filtering,
and trimming).

Station metadata is read from the ``STATION_XML`` file and the volcano table
is loaded via :func:`volc_alarms.utils.setup_utils.load_volcano_list` using
``VOLCANO_LIST`` environment variable
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
from obspy import Catalog, UTCDateTime, read_inventory
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.core.event import Event
from obspy.geodetics import gps2dist_azimuth
from tabulate import tabulate

from volc_alarms.utils.downloading import Earthscope_client
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)


def find_nearest_volcano(df, lon_col="longitude", lat_col="latitude", filter_col=None, volc_df=None):
    """Annotate each row with its nearest volcano and distance.

    For every row in ``df`` the nearest volcano (by great-circle distance) is
    found and written back as new ``v_distance`` and ``v_name`` columns.

    Parameters
    ----------
    df : pandas.DataFrame
        Points of interest (e.g. earthquakes, PIREP). Must contain the longitude 
        and latitude columns named by ``lon_col`` and ``lat_col``.
    lon_col : str, optional
        Name of the longitude column, by default ``"longitude"``.
    lat_col : str, optional
        Name of the latitude column, by default ``"latitude"``.
    filter_col : str, optional
        Per-alarm opt-in column in ``volc_df``; rows whose value is ``"N"`` are
        excluded from candidates. Ignored if the column is absent.
    volc_df : pandas.DataFrame, optional
        Volcano table to match against. If ``None``, loaded via
        :func:`volc_alarms.utils.setup_utils.load_volcano_list`.

    Returns
    -------
    pandas.DataFrame
        The input ``df`` with added ``v_distance`` (km) and ``v_name`` columns.
    """
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
        dist, *_ = gps2dist_azimuth(lat, lon, lat0, lon0)
        DIST = np.append(DIST, dist / 1000.0)
    volcs.loc[:, "distance"] = DIST

    volcs = volcs.sort_values("distance")

    return volcs


def addPhaseHint(cat):
    """Copy phase labels from arrivals onto their matching picks.

    For each event, matches every pick to the arrival that references it (by
    resource id) and sets the pick's ``phase_hint`` to the arrival's phase.

    Parameters
    ----------
    cat : obspy.Catalog
        Catalog whose events' picks should be annotated. Modified in place.

    Returns
    -------
    obspy.Catalog
        The same catalog, with ``phase_hint`` populated on matched picks.
    """
    for eq in cat: # Loop over catalog
        for pick in eq.picks: # Loop over picks
            nowPickID = pick.resource_id # Go get phase hint
            for arrival in eq.preferred_origin().arrivals:
                nowArrID = arrival.pick_id
                if nowPickID == nowArrID:
                    pick.phase_hint = arrival.phase
    return cat


def eq_picks_to_dataframe(cat):
    """Build a per-station DataFrame of pick metadata for an obspy `Catalog` 
    or obspy `Event`.

    Collects the unique stations that recorded picks, looks up each station's
    coordinates from EarthScope, and computes its distance to the event
    origin. ``P`` and ``S`` pick times are also attached per station.

    Parameters
    ----------
    cat : obspy.Catalog or obspy.core.event.Event
        Catalog or single Event whose picks should be summarized.

    Returns
    -------
    pandas.DataFrame
        One row per station with columns ``NS``, ``NSLC``, ``Latitude``,
        ``Longitude``, and ``Distance`` (km), sorted by distance. For a single
        event, ``P`` and ``S`` pick-time columns are included.
    """
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
            ns = f"{net}.{sta}"
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
    """Convert a reduced-displacement target into per-station RSAM levels.

    For a desired reduced displacement, computes the equivalent RSAM (counts)
    threshold at each station, accounting for station-to-volcano distance,
    instrument gain, and attenuation. The resulting levels are rounded to the
    nearest multiple of ``base`` and printed as a table.

    Exactly one of ``config`` or ``nslc_list`` provides the station set.

    Parameters
    ----------
    DR : float
        Target reduced displacement in cm^2.
    config : object, optional
        Alarm configuration exposing ``rsam_stations``, ``arrestor``, and
        ``volcano_name``. Used to build the ordered station list.
    nslc_list : str or list of str, optional
        Explicit NSLC channel(s) to use instead of ``config``.
    volcano : str, optional
        Target volcano name. Falls back to ``config.volcano_name`` when not
        given.
    base : int, optional
        Rounding base for the output RSAM levels, by default 25.

    Returns
    -------
    pandas.DataFrame or None
        Table with columns ``Station``, ``Volcano``, ``Distance (km)``,
        ``DR Level``, and ``RSAM Level``. Returns ``None`` if neither a volcano
        nor a station source could be resolved.
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
    rows = []
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

        rows.append(
            {
                "Station": nslc,
                "Volcano": volcano,
                "Distance (km)": round(R, 1),
                "DR Level": DR,
                "RSAM Level": lvl,
            }
        )

    table = pd.DataFrame(
        rows,
        columns=["Station", "Volcano", "Distance (km)", "DR Level", "RSAM Level"],
    )
    table_str = tabulate(
        table,
        headers="keys",
        tablefmt="simple",
        showindex=False,
        floatfmt="g",
    )
    print("\n" + table_str + "\n")

    return table


def add_metadata(st):
    """Attach station coordinates and inventory to each trace in a stream.

    Reads the StationXML file from environment variable ``STATION_XML`` and, 
    for every trace, selects the matching inventory and stores both the 
    coordinates and the inventory on ``tr.stats``.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose traces should be annotated. Modified in place.

    Returns
    -------
    obspy.Stream or None
        The stream with ``tr.stats.coordinates`` and ``tr.stats.inventory``
        populated for each trace, or ``None`` if the StationXML file is missing.
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
    """Demean, taper, bandpass filter, merge, and trim a stream.

    Applies the standard conditioning chain used before detection: remove the
    mean, taper, zero-phase bandpass filter between ``config.f1`` and
    ``config.f2``, merge (filling gaps with zeros), and trim to the requested
    window with zero padding. Any gaps or overlaps are logged.

    Parameters
    ----------
    st : obspy.Stream
        Raw stream to process. Modified in place.
    t1 : obspy.UTCDateTime
        Start of the output window.
    t2 : obspy.UTCDateTime
        End of the output window.
    config : object
        Configuration exposing ``taper`` (seconds), ``f1`` and ``f2`` (filter
        corner frequencies in Hz).

    Returns
    -------
    obspy.Stream
        The processed, trimmed stream.
    """
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
    """Remove instrument gain/sensitivity from traces in a stream.

    Note: inventory is stashed on ``tr.stats.inventory`` (not a bare
    ``tr.inventory`` attribute) since ``Trace.stats`` is deep-copied by
    ``Stream.merge()`` and ``Trace.copy()``, while arbitrary attributes
    set directly on a ``Trace`` object are not preserved by either.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose traces have an inventory attached via
        :func:`add_metadata`. Modified in place.

    Returns
    -------
    obspy.Stream
        The stream with instrument sensitivity removed. Traces lacking an
        attached inventory are left unchanged.
    """
    for tr in st:
        if "inventory" in tr.stats and tr.stats.inventory is not None:
            tr.remove_sensitivity(tr.stats.inventory)
        else: # pragma: no cover
            logger.warning(f"{tr.id}: no inventory attached. Skipping gain removal.")
    return st