import importlib
import io
import json
import os
import socket
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests
import urllib3
from dotenv import load_dotenv
from obspy import Catalog, Stream, Trace, UTCDateTime
from obspy.clients.earthworm import Client as EW_Client
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.io.quakeml.core import Unpickler

from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

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


def download_waveforms(nslc_list, T1, T2, fill_value=0, iris=False):
    """_summary_

    Parameters
    ----------
    nslc_list : _type_
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
    # nslc_list = list of station names in NSLC format (eg. ['AV.PS4A..BHZ','AV.PVV..BHZ','AV.PS1A..BHZ'])
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

    # TODO set up some default client. Maybe from .env? 
    if iris:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        client = FDSN_Client("IRIS")
    else:
        client = EW_Client(
            os.environ["WINSTON_HOST"],
            int(os.environ["WINSTON_PORT"]),
            timeout=int(os.environ["TIMEOUT"]),
        )


    start = time.time()
    for nslc in nslc_list:
        try:
            if iris:
                tr = client.get_waveforms(*nslc.split("."), T1, T2)
            else:
                tr = client.get_waveforms(*nslc.split("."), T1, T2, cleanup=True)
            if len(tr) > 1:
                logger.info("{:.0f} traces for {}".format(len(tr), nslc))
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
            logger.warning(f"Error grabbing data for {nslc}, filling with zeros")
            tr = Stream()
        # if no data, create a blank trace for that channel
        if not tr:
            logger.warning(f"No data for {nslc}. Filling with zeros")
            tr = Trace()
            tr.id = nslc
            tr.stats["sampling_rate"] = 100
            tr.stats["starttime"] = T1
            tr.data = np.zeros(
                int((T2 - T1) * tr.stats["sampling_rate"]), dtype="int32"
            )
        st += tr
    logger.info(f"{time.time() - start:.2f} seconds")

    logger.info("Detrending data...")
    st.detrend("demean")
    st.trim(T1, T2, pad=True, fill_value=0)
    return st


def download_lightning(force=False):

    logger.info("Reading in alerts from volcview api .json file")
    attempt = 1
    max_tries = 3
    lightning_url = os.getenv("LIGHTNING_URL")
    if force:
        logger.warning("Forcing trigger by pointing to global data source")
        lightning_url = lightning_url.replace("avorecent", "recent")
        lightning_url = lightning_url.replace("avo-volcview", "volcview")
    while attempt <= max_tries:
        try:
            data = json.load(
                os.popen(
                    'curl --connect-timeout 5 -H "username:{}" -H "password:{}" -X GET {}'.format(
                        os.getenv("API_USERNAME"),
                        os.getenv("API_PASSWORD"),
                        lightning_url,
                    )
                )
            )
            strokes_df = pd.DataFrame(data["lightning"])
            if len(strokes_df) >= 1:
                column_rename = {
                    "lightningLatitude": "latitude",
                    "lightningLongitude": "longitude",
                    "lightningDate": "time",
                    "lightningId": "id",
                    "dataSource": "dataSource",
                    "volcanoName": "api_vname",
                    "volcanoLatitude": "api_vlat",
                    "volcanoLongitude": "api_vlon",
                    "nearestDistanceKm": "api_vdist",
                }
                strokes_df.rename(columns=column_rename, inplace=True)
                strokes_df["time"] = pd.to_datetime(strokes_df["time"])
                strokes_df = strokes_df[column_rename.values()]
            break
        except Exception as e:
            logger.warning(f"Error getting data from Volcview-API on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            strokes_df = None

    return strokes_df


def download_cimss_vv_api():

    usr = os.getenv("API_USERNAME")
    pwd = os.getenv("API_PASSWORD")
    url = os.getenv("NOAA_CIMSS_URL")

    attempt = 1
    max_tries = 3
    while attempt <= max_tries:
        try:
            result = os.popen(
                f"curl --connect-timeout 5 --max-time 20 -H 'username:{usr}' -H 'password:{pwd}' -X GET {url}"
            )
            cimss_df = pd.read_json(result)
            break
        except Exception as e:
            logger.warning(f"Error getting data from Volcview-API on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            cimss_df = None
    return cimss_df


def download_pilot_reports(T0, config):

    volcs = load_volcano_list()
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
        with open(config.zipfile, "wb") as f:
            resp = requests.get(pirep_url, verify=False, timeout=10)
            f.write(resp.content)
    except Exception:
        logger.error("Request error from PIREP API")
        state = "WARNING"
        return state, archive

    if zipfile.is_zipfile(config.zipfile):
        archive = zipfile.ZipFile(config.zipfile, "r")
        logger.info("New pilot reports from API call")
    else:
        logger.info("No new pilot reports from API call")

    os.remove(config.zipfile)

    return state, archive


def scrape_cimss_alert(alert):
    from bs4 import BeautifulSoup

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


def get_cimss_image(soup, alert, config):

    base_url = "://".join(urlparse(alert.alert_url)[:2])
    image_files = soup.find(class_="alert_images").find_all("img")
    for i, img in enumerate(image_files):
        img.get("src")
        im_url = urljoin(base_url, img.get("src"))
        r = requests.get(im_url, verify=False, timeout=10)

        if r.status_code == 200:
            new_file = Path(str(config.img_file).replace(".png", f"{i+1:g}.png"))
            with open(new_file, "wb") as out:
                for bits in r.iter_content():
                    out.write(bits)


def download_vaa_from_nws_api():
    ## this is currently not implemented. Testing out mesonet as preferred option
    attempt = 1
    max_tries = 3
    vaa_id_list = None
    while attempt <= max_tries:
        try:
            response = requests.get(os.environ["VAA_URL"], timeout=10, verify=False)
            data = response.json()

            vaa_id_list = data["@graph"]
            break
        except Exception:		
            logger.warning('Page error on attempt number {:g}'.format(attempt))
            attempt += 1	
            if attempt == max_tries:
                logger.error(f'Problem connecting to VAA API after {max_tries} attempts')
                
    return vaa_id_list


def download_mesonet_vaa_list(T0):
    logger.info(
        f"Reading in alerts from mesonet api .json file for {T0.strftime('%Y-%m-%d')}"
    )

    vaa_url = os.getenv("VAA_URL") + f"&date={T0.strftime('%Y-%m-%d')}"

    attempt = 1
    max_tries = 3
    vaa_id_list = None
    while attempt <= max_tries:
        try:
            response = requests.get(vaa_url, timeout=10, verify=False)
            data = response.json()
            vaa_id_list = pd.DataFrame(data["data"])
            if not vaa_id_list.empty:
                vaa_id_list = vaa_id_list["text_link"].to_frame()
            else:
                vaa_id_list["text_link"] = ""
            break
        except Exception:
            logger.warning('Page error on attempt number {:g}'.format(attempt))
            attempt += 1	
            if attempt == max_tries:
                logger.error(f'Problem connecting to VAA API after {max_tries} attempts')
                
    return vaa_id_list


def download_SO2():
    from bs4 import BeautifulSoup

    logger.info("Reading SACS SO2 webpage")
    attempt = 1
    max_tries = 3
    while attempt <= max_tries:
        try:
            page = requests.get(os.getenv("SACS_URL"), verify=False, timeout=10)
            soup = BeautifulSoup(page.content, "html.parser")
            table = soup.find_all("pre")[0]
            break
        except Exception as e:
            logger.warning(f"Error scraping SO2 webpage on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            table = None

    return table, soup


def download_station_xml():
    """Download and update station metadata XML file from IRIS."""

    client = FDSN_Client("IRIS")

    files = list(Path(os.environ["CONFIGS_DIR"]).glob("*RSAM*.py", case_sensitive=False))
    files += list(Path(os.environ["CONFIGS_DIR"]).glob("*Tremor*.py", case_sensitive=False))
    files += list(Path(os.environ["CONFIGS_DIR"]).glob("*Infrasound*.py", case_sensitive=False))

    NSLC = []

    for file_path in files:
        file_name = Path(file_path).stem  # Get filename without extension
        spec = importlib.util.spec_from_file_location(file_name, file_path)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        logger.info(config)
        for nslc_dict in config.NSLC:
            NSLC.append(nslc_dict["nslc"])
    NSLC = np.array(NSLC)
    NSLC = np.unique(NSLC)

    logger.info("______ Begin Updating Metadata ______")
    for nslc in NSLC:
        logger.info(nslc)
        net, sta, loc, chan = nslc.split(".")
        if "inventory" not in locals():
            inventory = client.get_stations(
                network=net,
                station=sta,
                channel=chan,
                location=loc,
                level="response",
                starttime=UTCDateTime.utcnow(),
            )
        else:
            inventory += client.get_stations(
                network=net,
                station=sta,
                channel=chan,
                location=loc,
                level="response",
                starttime=UTCDateTime.utcnow(),
            )

    write_path = Path(os.environ["HOME_DIR"]) / "alarm_aux_files" / "stations.xml"
    inventory.write(write_path, format="STATIONXML")

    logger.info("^^^^^^ Finished Updating Metadata ^^^^^^")
    return
