import os
from pathlib import Path
from shutil import rmtree

import numpy as np
import pandas as pd
import shapefile
from dotenv import load_dotenv
from obspy import UTCDateTime, read_inventory
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.geodetics import gps2dist_azimuth
from pandas.errors import EmptyDataError

from .setup_utils import get_logger
from .downloading import IRIS_client

load_dotenv()

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


def check_ignore_volcano(cimss_df, config, alert_type=None):

    volcs = pd.read_excel(config.volc_file, index_col="Volcano")
    cimss_df["keep"] = True
    if alert_type is None:
        ALERT_TYPE = {"ash": "NOAA Ash", "hot": "NOAA Thermal", "ice": "NOAA Ice"}
        for i, row in cimss_df.iterrows():
            if volcs.loc[row.v_name, ALERT_TYPE[row.alert_type]] == "N":
                cimss_df.loc[i, "keep"] = False
    else:
        for i, row in cimss_df.iterrows():
            if volcs.loc[row.v_name, alert_type] == "N":
                cimss_df.loc[i, "keep"] = False

    return cimss_df


def write_to_csv(df, config, columns):

    logger.info(f"Writing {len(df)} events to {config.outfile}")
    df.to_csv(config.outfile, columns=columns, index=False, date_format='%Y-%m-%d %H:%M:%S.%f')

    return


def format_cimss_dataframe(cimss_df, config, T0):

    # update DataFrame with unique NOAA/CIMSS id
    # Remove rows with empty alert_url and extract NOAA_id
    cimss_df = cimss_df[cimss_df["alert_url"].notna() & (cimss_df["alert_url"] != "")]
    cimss_df["NOAA_id"] = pd.to_numeric(
        cimss_df["alert_url"].str.split("/").str[-1],
        errors="coerce",
        downcast="integer",
    )
    cimss_df = cimss_df[cimss_df["NOAA_id"].notna()]

    cimss_df["time"] = pd.to_datetime(cimss_df["object_date_time"])

    if len(cimss_df) > 0:
        cimss_df.loc[:, "aid"] = np.nan
        cimss_df = cimss_df.sort_values("time")

    return cimss_df


def pirep_archive_to_dataframe(T0, config, archive):

    T2 = T0
    T1 = T2 - config.duration

    archive.extractall(path=config.tmp_zipped_dir)
    T1_str = T1.strftime('%Y%m%d%H%M')
    T2_str = T2.strftime('%Y%m%d%H%M')
    shp_path = config.tmp_zipped_dir / f"pireps_{T1_str}_{T2_str}"

    # read file, parse out the records
    sf = shapefile.Reader(shp_path)
    fields = [x[0] for x in sf.fields][1:]
    records = sf.records()

    # convert to a DataFrame
    pirep_df = pd.DataFrame(columns=fields, data=records)
    pirep_df['VALID'] = pd.to_datetime(pirep_df['VALID'])
    pirep_df = pirep_df[pirep_df.LAT>49]
    pirep_df["time"] = pd.to_datetime(pirep_df["VALID"])
    pirep_df["lat"] = pirep_df["LAT"]
    pirep_df["lon"] = pirep_df["LON"]

    # delete duplicate events with different text versions in the 'REPORT' field'
    A = pirep_df.copy()
    del A['REPORT']
    A.drop_duplicates(inplace=True)
    pirep_df = pirep_df.loc[A.index]
    pirep_df.reset_index(drop=True, inplace=True)

    rmtree(config.tmp_zipped_dir)

    return pirep_df



    # new_pireps_df = update_event_list(
    #     pirep_df,
    #     config.outfile,
    #     ["time", "lat", "lon", "PROD_ID"],
    #     unique_id_col="PROD_ID",
    # )

    # n = len(pirep_df) - len(new_pireps_df)
    # logger.info(f"{n} old and {len(new_pireps_df)} new PIREP alerts.")

    # if len(new_pireps_df) > 0:
    #     new_pireps_df.loc[:, "aid"] = np.nan
    #     new_pireps_df = new_pireps_df.sort_values("time")


    # return new_pireps_df


def check_volcano_mention(df):
    df["trigger"] = False
    for i, row in df.iterrows():
        report = row["REPORT"].upper()
        tmp_report = report.replace("VAR", "")
        tmp_report = tmp_report.replace("VAL", "")
        tmp_report = tmp_report.replace("VAT", "")
        tmp_report = tmp_report.replace("NEVA", "")
        tmp_report = tmp_report.replace("AVAIL", "")
        tmp_report = tmp_report.replace("SVA", "")
        tmp_report = tmp_report.replace("PREVAIL", "")
        tmp_report = tmp_report.replace("VASI", "")
        tmp_report = tmp_report.replace("TOLOVANA", "")
        tmp_report = tmp_report.replace("GAVANSKI", "")
        tmp_report = tmp_report.replace("CORDOVA", "")
        tmp_report = tmp_report.replace("ADVANC", "")
        tmp_report = tmp_report.replace("INVAD", "")
        tmp_report = tmp_report.replace("VACINITY", "")
        tmp_report = tmp_report.replace("SULLIVAN", "")
        tmp_report = tmp_report.replace("BELIEVABLE", "")
        tmp_report = tmp_report.replace("DURD VA RWY", "")
        if (
            len(tmp_report.split("/SK")) > 1
            and "VA" in tmp_report.split("/SK")[-1].split("/")[0]
        ):
            df.loc[i, "trigger"] = True
        elif (
            len(tmp_report.split("/RM")) > 1
            and "VA" in tmp_report.split("/RM")[-1].split("/")[0]
        ):
            df.loc[i, "trigger"] = True

        trigger_words = [
            " ASH",
            "/ASH",
            "VOLC",
            "SULFUR",
            "SULPHUR",
            "PLUME",
            "ERUPT",
            "STEAM",
            "MAGMA",
            "PYROCLASTIC",
        ]

        if any(t_word in report for t_word in trigger_words):
            df.loc[i, "trigger"] = True

    return df


def find_nearest_volcano(df, config, lon_col="longitude", lat_col="latitude"):

    VOLCS = pd.read_excel(config.volc_file)
    V_DIST = []
    V_NAME = []

    for _, row in df.iterrows():
        volcs = volcano_distance(row[lon_col], row[lat_col], VOLCS)
        V_DIST.append(volcs.iloc[0].distance)
        V_NAME.append(volcs.iloc[0].Volcano)

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


def eq_picks_to_dataframe(eq):

    client = IRIS_client()

    NS = []
    NSLC = []
    SCNL = []
    LATS = []
    LONS = []
    DIST = []

    for p in eq.picks:
        wid = p.waveform_id
        net, sta, loc, chan = wid.id.split(".")
        ns = ".".join([net, sta])
        if ns not in NS:
            logger.info(f"Getting lat/lon info for {wid.id}")
            inventory = client.get_stations(
                network=net, station=sta, location=loc, channel=chan
            )
            # NSLC.append(wid.id.replace('..','.--.'))
            NS.append(ns)
            NSLC.append(wid.id)
            SCNL.append(".".join([sta, chan, net, loc]))
            LATS.append(inventory[0][0].latitude)
            LONS.append(inventory[0][0].longitude)
    for i, nslc in enumerate(NSLC):
        dist = (
            gps2dist_azimuth(
                eq.preferred_origin().latitude,
                eq.preferred_origin().longitude,
                LATS[i],
                LONS[i],
            )[0]
            / 1000.0
        )
        DIST.append(dist)

    STAS = pd.DataFrame(
        {
            "NS": NS,
            "NSLC": NSLC,
            "SCNL": SCNL,
            "Latitude": LATS,
            "Longitude": LONS,
            "Distance": DIST,
        }
    )

    STAS["P"] = np.nan
    STAS["S"] = np.nan
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
    home_dir = Path(os.environ["HOME_DIR"])

    VELOCITY = 1.5  # km/s
    FREQ = 2  # dominant frequency (Hz)
    Q = 200  # quality factor

    T0 = UTCDateTime.utcnow()
    VOLCS = pd.read_excel(home_dir / "alarm_aux_files" / "volcano_list.xlsx")
    volcs = VOLCS[VOLCS["Volcano"] == volcano_name].copy()
    SCNL = pd.DataFrame.from_dict(config.SCNL)

    for scnl in SCNL.scnl:
        sta, chan, net, loc = scnl.split(".")
        inventory = client.get_stations(
            network=net,
            station=sta,
            channel=chan,
            location=loc,
            starttime=T0,
            endtime=T0,
            level="response",
        )

        tr_id = ".".join((net, sta, loc, chan)).replace("--", "")
        coords = inventory.get_coordinates(tr_id)
        gain = inventory.get_response(
            tr_id, T0
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

        logger.info("{}: {:g}".format(scnl, lvl))

    return


def RSAM_to_DR(tr, volcano_name, VELOCITY=1.5, FREQ=2, Q=200):
    """_summary_



    VELOCITY = 1.5 	# km/s
    FREQ = 2 		# dominant frequency (Hz)
    Q = 200			# quality factor

    Parameters
    ----------
    tr : _type_
        _description_
    volcano_name : _type_
        _description_
    VELOCITY : float, optional
        _description_, by default 1.5
    FREQ : int, optional
        _description_, by default 2
    Q : int, optional
        _description_, by default 200

    Returns
    -------
    _type_
        _description_


    """

    home_dir = Path(os.environ["HOME_DIR"])
    VOLCS = pd.read_excel(home_dir / "alarm_aux_files" / "volcano_list.xlsx")

    volcs = VOLCS[VOLCS["Volcano"] == volcano_name].copy()

    tr.id = tr.id.replace("--", "")
    inventory = read_inventory(home_dir / "alarm_aux_files" / "stations.xml")

    coords = inventory.get_coordinates(tr.id)
    gain = inventory.get_response(
        tr.id, tr.stats.starttime
    ).instrument_sensitivity.value  # counts/m/s

    volcs = volcano_distance(coords["longitude"], coords["latitude"], volcs)
    R = volcs.iloc[0].distance

    r = R * 1000 * 100
    velocity = VELOCITY * 1000 * 100
    wavelength = velocity / FREQ

    #### account for attenuation ####
    numerator = -np.pi * FREQ * r
    denominator = Q * velocity
    atten_factor = np.exp(numerator / denominator)

    lvl = np.sqrt(np.mean(np.square(tr.data)))  # rms level in counts
    rms_v = lvl / (gain * atten_factor)         # rms in m/s corrected for gain & attenuation
    rmssta = rms_v * 100 / (2 * np.pi * FREQ)   # converted to cm
    DR = rmssta * np.sqrt(r * wavelength)       # converted to reduced displacement

    return DR