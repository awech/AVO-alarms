import io
import os
import socket
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import urllib3
import yaml
from obspy import Catalog, Stream, Trace, UTCDateTime
from obspy.clients.earthworm import Client as EW_Client
from obspy.clients.fdsn import Client as FDSN_Client
from obspy.io.quakeml.core import Unpickler

from avo_alarms.utils.setup_utils import get_logger

urllib3.disable_warnings()
socket.setdefaulttimeout(15)

logger = get_logger(__name__)


def IRIS_client():

    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    
    attempt = 1
    while attempt <= 3:
        try:
            client = FDSN_Client("EARTHSCOPE")
            break
        except Exception as e:
            logger.warning(f"Earthscope client connection attempt {attempt} failed: {e}")
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
            catalog_df = catalog_df.rename(columns={"id": "event_id"})
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
                logger.info(f"{len(tr):.0f} traces for {nslc}")
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
            logger.warning(f"Page error on attempt number {attempt:g}")
            attempt += 1	
            if attempt == max_tries:
                logger.error(f"Problem connecting to VAA API after {max_tries} attempts")
                
    return vaa_id_list


def _extract_nslc_from_config(config):
    """Extract NSLC identifiers from a single parsed YAML config (canonical schema).

    The canonical schema differs per seismic alarm:
      - RSAM: ``rsam_stations[*].nslc`` + ``infrasound[*]`` (plain strings)
        + ``arrestor.nslc``.
      - Tremor / Infrasound: ``nslc[*]`` as plain strings.

    Parameters
    ----------
    config : dict
        The mapping produced by ``yaml.safe_load`` for one config file.

    Returns
    -------
    list of str
        The NSLC strings found in this config (not de-duplicated).
    """
    nslc = []

    # RSAM-shaped config
    if "rsam_stations" in config:
        for station in config.get("rsam_stations", []):
            nslc.append(station["nslc"])
        # infrasound channels are plain NSLC strings (plot-only)
        for channel in config.get("infrasound", []):
            nslc.append(channel)
        # arrestor is a single mapping with an nslc key
        arrestor = config.get("arrestor")
        if arrestor is not None:
            nslc.append(arrestor["nslc"])

    # Tremor / Infrasound: top-level `nslc` is a list of plain strings
    elif "nslc" in config:
        for entry in config["nslc"]:
            nslc.append(entry)

    return nslc


def _collect_station_nslc(configs_dir):
    """Glob the RSAM/Tremor/Infrasound `.yml` configs and collect unique NSLC.

    Parameters
    ----------
    configs_dir : str or Path
        Directory containing the alarm `.yml` config files (``CONFIGS_DIR``).

    Returns
    -------
    numpy.ndarray
        The sorted, de-duplicated union of NSLC across the seismic alarm configs.
    """
    configs_dir = Path(configs_dir)
    files = list(configs_dir.glob("*RSAM*.yml", case_sensitive=False))
    files += list(configs_dir.glob("*Tremor*.yml", case_sensitive=False))
    files += list(configs_dir.glob("*Infrasound*.yml", case_sensitive=False))

    NSLC = []
    for file_path in files:
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)
        logger.info(file_path)
        NSLC.extend(_extract_nslc_from_config(config))

    NSLC = np.array(NSLC)
    NSLC = np.unique(NSLC)
    return NSLC


def download_station_xml():
    """Download and update station metadata XML file from IRIS."""

    client = IRIS_client()

    NSLC = _collect_station_nslc(os.environ["CONFIGS_DIR"])

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
        time.sleep(0.25)

    out_file = Path(os.environ["STATION_XML"])
    tmp_outfile = out_file.with_suffix(".tmp")
    inventory.write(tmp_outfile, format="STATIONXML")
    os.replace(tmp_outfile, out_file)

    logger.info("^^^^^^ Finished Updating Metadata ^^^^^^")
    return
