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

from volc_alarms.utils.setup_utils import get_logger

urllib3.disable_warnings()
socket.setdefaulttimeout(15)

logger = get_logger(__name__)


def Earthscope_client():

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


def _qc_sub_trace(sub_trace):
    """
    Ensure consistent data type and sampling rate for a trace.

    Casts trace data to int32 if not already, and rounds the sampling
    rate to the nearest integer if it is not already a whole number.

    Args:
        sub_trace (obspy.Trace): A single seismic trace to check.

    Returns:
        obspy.Trace: The trace with corrected data type and sampling rate.
    """
    if sub_trace.data.dtype.name != "int32":
        sub_trace.data = sub_trace.data.astype("int32")
    if sub_trace.stats.sampling_rate != np.round(sub_trace.stats.sampling_rate):
        sub_trace.stats.sampling_rate = np.round(sub_trace.stats.sampling_rate)
    return sub_trace


def download_waveforms(nslc_list, T1, T2):
    """Download waveform data for a list of NSLC channels.

    Uses the Earthscope FDSN client if the ``USE_EARTHSCOPE`` environment
    variable is set using the `--earthscope` flag, otherwise connects 
    to datasource listed in the .env file

    Parameters
    ----------
    nslc_list : list of str
        Station names in N.S.L.C format (e.g. ['AV.PS4A..BHZ']).
    T1 : obspy.UTCDateTime
        Start time.
    T2 : obspy.UTCDateTime
        End time.

    Returns
    -------
    obspy.Stream
        Stream of traces, one per requested channel.
    """
    T1_str = T1.strftime("%Y.%m.%d %H:%M:%S")
    T2_str = T2.strftime("%Y.%m.%d %H:%M:%S")
    logger.info(f"{T1_str} - {T2_str}")
    logger.info("Grabbing data...")

    st = Stream()

    if os.environ.get("USE_EARTHSCOPE"):
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
        client = FDSN_Client("earthscope")
    else:
        client = EW_Client(
            os.environ["WINSTON_HOST"],
            int(os.environ["WINSTON_PORT"]),
            timeout=int(os.environ["TIMEOUT"]),
        )


    for nslc in nslc_list:
        try:
            tr = client.get_waveforms(*nslc.split("."), T1, T2)
            if len(tr) > 1: # pragma: no cover
                # Handle cases with multiple traces (e.g., due to gaps)
                for sub_trace in tr:
                    # Ensure consistent data types and sampling rates
                    sub_trace = _qc_sub_trace(sub_trace)
                if not tr.get_gaps():
                    # handle case where multiple traces returned with no gaps between them
                    logger.info(f"{nslc}: Multiple traces returned with no gaps between. Simple merge")
                    tr.merge()

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

    client = Earthscope_client()

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
