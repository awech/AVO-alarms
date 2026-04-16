import importlib
import io
import json
import os
import socket
import time
import zipfile
from glob import glob
from pathlib import Path
from shutil import rmtree

import numpy as np
import pandas as pd
import requests
import shapefile
import urllib3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from obspy import Catalog, Stream, Trace, UTCDateTime, read_inventory
from obspy.clients.earthworm import Client as EW_Client
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.geodetics import gps2dist_azimuth
from obspy.io.quakeml.core import Unpickler
from pandas.errors import EmptyDataError

from .setup_utils import get_logger

load_dotenv()
urllib3.disable_warnings()
socket.setdefaulttimeout(15)

logger = get_logger(__name__)


def IRIS_client():
    attempt = 1
    while attempt <= 3:
        try:
            client = FDSN_Client("IRIS")
            break
        except Exception as e:
            logger.warning(f"IRIS client connection attempt {attempt} failed: {e}")
            time.sleep(2)
            attempt += 1
            client = None
    return client


def download_hypocenters(URL):
    """_summary_

    Returns
    -------
    _type_
        _description_
    """

    urllib3.disable_warnings()

    attempt = 1
    while attempt <= 3:
        try:
            res = requests.get(URL, verify=False, timeout=10)
            body = res.content
            break
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(2)
            attempt += 1
            body = None

    if not body:
        return None

    try:
        CAT = Unpickler().loads(body)
    except Exception:
        CAT = Catalog()
        logger.warning("No events!")

    return CAT


def download_hypocenters_csv(URL):
    attempt = 1
    success = False
    max_attempts = 3
    while attempt <= max_attempts:
        try:
            body = requests.get(URL, verify=False).content
            catalog_df = pd.read_csv(io.StringIO(body.decode('utf-8')), parse_dates=["time"])
            # catalog_df["id"] = catalog_df.apply(lambda x: x.net.lower() + str(x.id), axis=1)
            if len(catalog_df) > 0:
                catalog_df["time"] = catalog_df.apply(lambda x: UTCDateTime(x.time).strftime("%Y-%m-%d %H:%M:%S.%f"), axis=1)
                catalog_df["time"] = pd.to_datetime(catalog_df["time"])
            success = True
            break
        except Exception as e:
            logger.warning(f"Error downloading earthquake data on attempt {attempt}: {e}")
            time.sleep(2)
            attempt+=1
    if not success:
        logger.error(f"Failed to download earthquake data after {max_attempts} attempts.")
        catalog_df = None
    else:
        return catalog_df


def download_hypocenter_xml(URL):
    """_summary_

    Returns
    -------
    _type_
        _description_
    """

    urllib3.disable_warnings()

    attempt = 1
    while attempt <= 3:
        try:
            res = requests.get(URL, verify=False, timeout=10)
            body = res.content
            break
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(2)
            attempt += 1
            body = None

    if not body:
        return None

    try:
        CAT = Unpickler().loads(body)
    except Exception:
        CAT = Catalog()
        logger.warning("No events!")

    return CAT


def grab_data(scnl, T1, T2, fill_value=0):
    """_summary_

    Parameters
    ----------
    scnl : _type_
        _description_
    T1 : _type_
        _description_
    T2 : _type_
        _description_
    fill_value : int, optional
        _description_, by default 0

    Returns
    -------
    _type_
        _description_
    """
    # scnl = list of station names (eg. ['PS4A.EHZ.AV.--','PVV.EHZ.AV.--','PS1A.EHZ.AV.--'])
    # T1 and T2 are start/end obspy UTCDateTimes
    # fill_value can be 0 (default), 'latest', or 'interpolate'
    #
    # returns stream of traces with gaps accounted for
    #
    T1_str = T1.strftime("%Y.%m.%d %H:%M:%S")
    T2_str = T2.strftime("%Y.%m.%d %H:%M:%S")
    logger.info(f"{T1_str} - {T2_str}")
    logger.info("Grabbing data...")

    st = Stream()

    t_test1 = UTCDateTime.now()
    for sta in scnl:
        client = EW_Client(
            os.environ["WINSTON_HOST"],
            int(os.environ["WINSTON_PORT"]),
            timeout=int(os.environ["TIMEOUT"]),
        )
        if sta.split(".")[2] in ["HV", "AM"]:
            client = EW_Client(
                os.environ["NEIC_HOST"],
                int(os.environ["NEIC_PORT"]),
                timeout=int(os.environ["TIMEOUT"]),
            )

        try:
            tr = client.get_waveforms(
                sta.split(".")[2],
                sta.split(".")[0],
                sta.split(".")[3],
                sta.split(".")[1],
                T1,
                T2,
                cleanup=True,
            )
            if len(tr) > 1:
                logger.info("{:.0f} traces for {}".format(len(tr), sta))
                if fill_value == 0 or fill_value is None:
                    tr.detrend("demean")
                    tr.taper(max_percentage=0.01)
                for sub_trace in tr:
                    # deal with error when sub-traces have different dtypes
                    if sub_trace.data.dtype.name != "int32":
                        sub_trace.data = sub_trace.data.astype("int32")
                    if sub_trace.data.dtype != np.dtype("int32"):
                        sub_trace.data = sub_trace.data.astype("int32")
                    # deal with rare error when sub-traces have different sample rates
                    if sub_trace.stats.sampling_rate != np.round(
                        sub_trace.stats.sampling_rate
                    ):
                        sub_trace.stats.sampling_rate = np.round(
                            sub_trace.stats.sampling_rate
                        )
                logger.info("Merging gappy data...")
                tr.merge(fill_value=fill_value)
        except Exception:
            logger.warning(f"Error grabbing data for {sta}, filling with zeros")
            tr = Stream()
        # if no data, create a blank trace for that channel
        if not tr:
            logger.warning(f"No data for {sta}. Filling with zeros")
            tr = Trace()
            tr.stats["station"] = sta.split(".")[0]
            tr.stats["channel"] = sta.split(".")[1]
            tr.stats["network"] = sta.split(".")[2]
            tr.stats["location"] = sta.split(".")[3]
            tr.stats["sampling_rate"] = 100
            tr.stats["starttime"] = T1
            tr.data = np.zeros(
                int((T2 - T1) * tr.stats["sampling_rate"]), dtype="int32"
            )
        st += tr
    logger.info("{} seconds".format(UTCDateTime.now() - t_test1))

    logger.info("Detrending data...")
    st.detrend("demean")
    st.trim(T1, T2, pad=True, fill_value=0)
    return st


def download_lightning():

    logger.info("Reading in alerts from volcview api .json file")
    attempt = 1
    max_tries = 3
    while attempt <= max_tries:
        try:
            data = json.load(
                os.popen(
                    'curl --connect-timeout 5 -H "username:{}" -H "password:{}" -X GET {}'.format(
                        os.environ["API_USERNAME"],
                        os.environ["API_PASSWORD"],
                        os.environ["LIGHTNING_URL"],
                    )
                )
            )
            A = pd.DataFrame(data["lightning"])
            break
        except Exception as e:
            logger.warning(f"Error getting data from Volcview-API on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            A = None

    return A


def download_cimss_vv_api():
    attempt = 1
    max_tries = 3
    while attempt <= max_tries:
        try:
            usr = os.getenv("API_USERNAME")
            pwd = os.getenv("API_PASSWORD")
            url = os.getenv("NOAA_CIMSS_URL")
            result = os.popen(
                f"curl --connect-timeout 5 --max-time 20 -H 'username:{usr}' -H 'password:{pwd}' -X GET {url}"
            ).read()
            cimss_df = pd.read_json(result)
            break
        except Exception as e:
            logger.warning(f"Error getting data from Volcview-API on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            cimss_df = None
    return cimss_df


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

    logger.info(f"{old_events_df} old and {len(new_events_df)} new events")

    return new_events_df, df


def get_recent_cimss_alerts(cimss_df, config, T0):

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


    cimss_df = find_nearest_volcano(cimss_df, config, lon_col="lon_rc", lat_col="lat_rc")
    cimss_df = cimss_df[
        cimss_df["v_distance"] < getattr(config, "max_distance", 25)
    ] # fiter dataframe to events < `max_distance` km from a volcano

    cimss_df = cimss_df.loc[
        cimss_df["time"] > (T0 - 3600 * 12).strftime("%Y-%m-%d %H:%M")
    ]  # limit DataFrame to alerts in the past 12 hours

    new_alerts_df = update_event_list(cimss_df, config.outfile, ["time", "NOAA_id", "vv_id"], unique_id_col="NOAA_id")

    n = len(cimss_df) - len(new_alerts_df)
    logger.info(f"{n} old and {len(new_alerts_df)} new NOAA CIMSS alerts.")

    if len(new_alerts_df) > 0:
        new_alerts_df.loc[:, "aid"] = np.nan
        new_alerts_df = new_alerts_df.sort_values("time")

    return new_alerts_df


def scrape_cimss_alert(alert):

    attempt = 1
    max_tries = 3

    while attempt <= max_tries:
        try:
            soup = BeautifulSoup(
                requests.get(alert.alert_url, verify=False, timeout=10).content
            )
            redir = soup.select_one("#loginform-custom")["action"]

            # This URL will be the URL that your login form points to with the "action" tag.
            POST_LOGIN_URL = redir
            # This URL is the page you actually want to pull down with requests.
            REQUEST_URL = alert.alert_url

            payload = {"log": os.environ["CIMSS_USERNAME"], "pwd": os.environ["CIMSS_PASSWORD"]}

            with requests.Session() as session:
                session.post(POST_LOGIN_URL, data=payload, verify=False, timeout=10)
                r = session.get(REQUEST_URL, verify=False, timeout=10)
                soup = BeautifulSoup(r.content)
            session.close()
            break
        except Exception:
            logger.warning(f"Error scraping NOAA CIMSS alert on attempt {attempt:g}")
            if attempt == max_tries:
                soup = None
            attempt += 1

    return soup


def download_pilot_reports(T0, config):

    volcs = pd.read_excel(config.volc_file)
    volcs = volcs[volcs["PIREP"] == "Y"]

    T2 = T0
    T1 = T2 - config.duration
    t1 = "&year1={}&month1={}&day1={}&hour1={}&minute1={}".format(
        T1.strftime("%Y"),
        T1.strftime("%m"),
        T1.strftime("%d"),
        T1.strftime("%H"),
        T1.strftime("%M"),
    )
    t2 = "&year2={}&month2={}&day2={}&hour2={}&minute2={}".format(
        T2.strftime("%Y"),
        T2.strftime("%m"),
        T2.strftime("%d"),
        T2.strftime("%H"),
        T2.strftime("%M"),
    )
    pirep_url = f"{os.getenv('PIREP_URL')}?fmt=shp{t1}{t2}"

    state = "OK"
    archive = None
    try:
        with open(config.zipfilename, "wb") as f:
            resp = requests.get(pirep_url, verify=False, timeout=10)
            f.write(resp.content)
    except Exception:
        logger.error("Request error from PIREP API")
        state = "WARNING"
        return state, archive

    if zipfile.is_zipfile(config.zipfilename):
        archive = zipfile.ZipFile(config.zipfilename, "r")
        logger.info("New pilot reports from API call")
    else:
        logger.info("No new pilot reports from API call")

    os.remove(config.zipfilename)

    return state, archive


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


def update_stationXML():
    """_summary_"""

    client = FDSN_Client("IRIS")

    seismic_dir = Path(os.environ["CONFIGS_DIR"]) / "*RSAM*.py"
    infra_dir = Path(os.environ["CONFIGS_DIR"]) / "*Infrasound*.py"
    files = glob(str(seismic_dir)) + glob(str(infra_dir))
    SCNL = []

    for file_path in files:
        file_name = Path(file_path).stem  # Get filename without extension
        spec = importlib.util.spec_from_file_location(file_name, file_path)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        logger.info(config)
        for scnl in config.SCNL:
            SCNL.append(scnl["scnl"])
    SCNL = np.array(SCNL)
    SCNL = np.unique(SCNL)

    logger.info("______ Begin Updating Metadata ______")
    for scnl in SCNL:
        logger.info(scnl)
        sta, chan, net, loc = scnl.split(".")
        if "inventory" not in locals():
            inventory = client.get_stations(
                station=sta,
                network=net,
                channel=chan,
                location=loc,
                level="response",
                starttime=UTCDateTime.utcnow(),
            )
        else:
            inventory += client.get_stations(
                station=sta,
                network=net,
                channel=chan,
                location=loc,
                level="response",
                starttime=UTCDateTime.utcnow(),
            )

    write_path = Path(os.environ["HOME_DIR"]) / "alarm_aux_files" / "stations.xml"
    inventory.write(write_path, format="STATIONXML")
    # inventory.write(os.environ['HOME_DIR']+'/alarm_aux_files/stations.xml',format='STATIONXML')

    logger.info("^^^^^^ Finished Updating Metadata ^^^^^^")
    return


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