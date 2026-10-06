"""
Data-acquisition helpers for the alarms package.

Collects the routines that reach out to external services: FDSN/Earthworm
waveform retrieval, earthquake hypocenter catalogs (CSV and QuakeML), Volcanic
Ash Advisory feeds, and station metadata (StationXML) downloads. Network calls
retry a few times and degrade gracefully (returning ``None`` or zero-filled
traces) rather than raising, so an upstream outage does not crash an alarm run.

Connection details (hosts, ports, timeouts, URLs) are read from environment
variables such as ``WINSTON_HOST``, ``FDSN_TIMEOUT``, ``VAA_URL``,
``CONFIGS_DIR``, and ``STATION_XML``.
"""

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
from obspy.clients.fdsn.header import FDSNException, FDSNNoDataException
from obspy.core.inventory.inventory import Inventory
from obspy.io.quakeml.core import Unpickler

from volc_alarms.utils.setup_utils import get_logger

urllib3.disable_warnings()

# Default socket timeout for legacy clients (earthworm, etc.)
socket.setdefaulttimeout(15)

# Timeout (in seconds) for obspy FDSN client HTTP operations.
FDSN_TIMEOUT = int(os.environ.get("FDSN_TIMEOUT", "60"))

logger = get_logger(__name__)


def Earthscope_client():
    """Create an FDSN client for the EarthScope data center.

    Retries up to three times, waiting two seconds between attempts.

    Returns
    -------
    obspy.clients.fdsn.Client or None
        A connected EarthScope FDSN client, or ``None`` if all attempts fail.
    """
    attempt = 1
    while attempt <= 3:
        try:
            client = FDSN_Client("earthscope", timeout=FDSN_TIMEOUT)
            break
        except (FDSNException, requests.exceptions.RequestException, OSError) as e:
            logger.warning(f"Earthscope client connection attempt {attempt} failed: {e}")
            time.sleep(2)
            attempt += 1
            client = None
    return client


def download_hypocenters_csv(URL):
    """Download an earthquake hypocenter catalog from a CSV endpoint.

    Retries up to three times. On success the ``time`` column is parsed to
    pandas datetimes and the ``id`` column is renamed to ``event_id``.

    Parameters
    ----------
    URL : str
        URL of the CSV catalog endpoint.

    Returns
    -------
    pandas.DataFrame or None
        The parsed catalog, or ``None`` if all download attempts fail.
    """
    attempt = 1
    success = False
    max_attempts = 3
    while attempt <= max_attempts:
        try:
            body = requests.get(URL, verify=True, timeout=10).content
            catalog_df = pd.read_csv(io.StringIO(body.decode('utf-8')), parse_dates=["time"])
            # catalog_df["id"] = catalog_df.apply(lambda x: x.net.lower() + str(x.id), axis=1)
            if len(catalog_df) > 0:
                catalog_df["time"] = catalog_df.apply(lambda x: UTCDateTime(x.time).strftime("%Y-%m-%d %H:%M:%S.%f"), axis=1)
                catalog_df["time"] = pd.to_datetime(catalog_df["time"])
            success = True
            catalog_df = catalog_df.rename(columns={"id": "event_id"})
            break
        except (requests.RequestException, OSError, ValueError, KeyError, UnicodeDecodeError) as e:
            logger.warning(f"Error downloading earthquake data on attempt {attempt}: {e}")
            time.sleep(2)
            attempt+=1
    if not success:
        logger.error(f"Failed to download earthquake data after {max_attempts} attempts.")
        catalog_df = None
    else:
        return catalog_df


def download_hypocenter_xml(URL):
    """Download an earthquake catalog from a QuakeML endpoint.

    Retries the HTTP request up to three times. The response body is parsed
    with ObsPy's QuakeML unpickler; if parsing fails, an empty catalog is
    returned.

    Parameters
    ----------
    URL : str
        URL of the QuakeML catalog endpoint.

    Returns
    -------
    obspy.Catalog or None
        The parsed catalog (possibly empty), or ``None`` if the request fails
        to return a body.
    """

    urllib3.disable_warnings()

    attempt = 1
    while attempt <= 3:
        try:
            res = requests.get(URL, verify=True, timeout=10)
            body = res.content
            break
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(2)
            attempt += 1
            body = None

    if not body:
        return None

    try:
        CAT = Unpickler().loads(body)
    except Exception:  # noqa: BLE001
        CAT = Catalog()
        logger.warning("No events!")

    return CAT


def _qc_sub_trace(sub_trace):
    """Ensure consistent data type and sampling rate for a trace.

    Casts trace data to int32 if not already, and rounds the sampling
    rate to the nearest integer if it is not already a whole number.

    Parameters
    ----------
    sub_trace : obspy.Trace
        A single seismic trace to check.

    Returns
    -------
    obspy.Trace
        The trace with corrected data type and sampling rate.
    """
    if sub_trace.data.dtype.name != "int32":
        sub_trace.data = sub_trace.data.astype("int32")
    if sub_trace.stats.sampling_rate != np.round(sub_trace.stats.sampling_rate):
        sub_trace.stats.sampling_rate = np.round(sub_trace.stats.sampling_rate)
    return sub_trace


def download_waveforms(nslc_list, T1, T2):
    """Download waveform data for a list of NSLC channels.

    Uses the EarthScope FDSN client if the ``USE_EARTHSCOPE`` environment
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
        client = FDSN_Client("earthscope", timeout=FDSN_TIMEOUT)
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

        except Exception:  # noqa: BLE001
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
    """Fetch the list of Volcanic Ash Advisories from the NWS API.

    Retries up to three times. A ``User-Agent`` header is sent because
    api.weather.gov rejects requests without one. Not currently wired into
    the active VAA workflow (Mesonet is the preferred source), but retained
    as backup in case of future need to switch to NWS source.

    Returns
    -------
    list or None
        The ``@graph`` list of VAA entries from the API response, or ``None``
        if all attempts fail.
    """
    ## this is currently not implemented. Testing out mesonet as preferred option
    attempt = 1
    max_tries = 3
    vaa_id_list = None
    # api.weather.gov rejects requests without a User-Agent (returns 403). NWS
    # asks that it identify the application, ideally with a contact address.
    headers = {"User-Agent": os.environ.get("NWS_API_USER_AGENT", "avo-alarms (volcano monitoring)")}
    while attempt <= max_tries:
        try:
            response = requests.get(
                os.environ["VAA_URL"], timeout=10, verify=True, headers=headers
            )
            data = response.json()

            vaa_id_list = data["@graph"]
            break
        except (requests.RequestException, OSError, ValueError, KeyError):
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

    # Read once with .get() so a config missing alarm_type (or a non-seismic
    # alarm) falls through to the empty list instead of raising.
    alarm_type = config.get("alarm_type")

    # RSAM-shaped config
    if alarm_type == "RSAM":
        for station in config.get("rsam_stations", []):
            nslc.append(station["nslc"])
        # infrasound channels are plain NSLC strings (plot-only)
        nslc.extend(config.get("infrasound", []))
        # arrestor is a single mapping with an nslc key
        arrestor = config.get("arrestor")
        if arrestor is not None:
            nslc.append(arrestor["nslc"])

    # Tremor / Infrasound: top-level `nslc` is a list of plain strings
    elif alarm_type in ("Infrasound", "Tremor"):
        nslc.extend(config.get("nslc", []))

    return nslc


def _collect_station_nslc(configs_dir):
    """Glob all `.yml` configs and collect unique NSLC.

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
    files = list(configs_dir.glob("*.yml"))

    NSLC = []
    for file_path in files:
        with open(file_path, "r") as f:
            config = yaml.safe_load(f)
        # Skip files that don't represent a valid alarm config.
        if not isinstance(config, dict) or "alarm_type" not in config:
            continue
        logger.info(file_path)
        NSLC.extend(_extract_nslc_from_config(config))

    NSLC = np.array(NSLC)
    NSLC = np.unique(NSLC)
    return NSLC


def download_station_xml():
    """Rebuild the local StationXML metadata file from Earthscope.

    Gathers the unique set of NSLC channels used by the seismic alarms by
    scanning the config directory (``CONFIGS_DIR``), then queries the
    EarthScope FDSN service for response-level metadata for each channel. The
    current station epoch is requested first; if none is available for a
    channel (``FDSNNoDataException``), all epochs are fetched instead. A short
    pause is inserted between requests to avoid hammering the service.

    The combined inventory is written to a temporary file and then atomically
    moved into place at ``STATION_XML`` via ``os.replace``, so a partially
    written file never overwrites the existing metadata.

    Notes
    -----
    Reads the ``CONFIGS_DIR`` and ``STATION_XML`` environment variables and
    writes to the ``STATION_XML`` path as a side effect. Returns nothing.
    """

    client = Earthscope_client()

    NSLC = _collect_station_nslc(os.environ["CONFIGS_DIR"])

    logger.info("______ Begin Updating Metadata ______")
    inventory = Inventory()
    for nslc in NSLC:
        logger.info(nslc)
        net, sta, loc, chan = nslc.split(".")
        try:
            inv = client.get_stations(
                network=net, station=sta, channel=chan, location=loc,
                level="response", starttime=UTCDateTime.utcnow(),
            )
        except FDSNNoDataException:
            logger.warning(f"{nslc}: no current epoch found. Fetching all epochs.")
            inv = client.get_stations(
                network=net, station=sta, channel=chan, location=loc,
                level="response",
            )
        inventory += inv
        time.sleep(0.25)

    out_file = Path(os.environ["STATION_XML"])
    tmp_outfile = out_file.with_suffix(".tmp")
    inventory.write(tmp_outfile, format="STATIONXML")
    os.replace(tmp_outfile, out_file)

    logger.info("^^^^^^ Finished Updating Metadata ^^^^^^")