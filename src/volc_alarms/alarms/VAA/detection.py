import os
import re
import time

import numpy as np
import pandas as pd
import requests
from obspy.geodetics.base import gps2dist_azimuth

from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def download_mesonet_vaa_list(T0, max_tries=3, timeout=10, backoff=2):
    """Download the mesonet VAA advisory list for a given date.

    Returns a single-column ``text_link`` DataFrame on success (which may be
    empty if there are no advisories for that date), or ``None`` if the API
    could not be reached / parsed after ``max_tries`` attempts.
    """
    logger.info(
        f"Reading in alerts from mesonet api .json file for {T0.strftime('%Y-%m-%d')}"
    )

    base_url = os.getenv("VAA_URL")
    if not base_url:
        logger.error("VAA_URL is not set; cannot download VAA list")
        return None
    vaa_url = base_url + f"&date={T0.strftime('%Y-%m-%d')}"

    for attempt in range(1, max_tries + 1):
        try:
            response = requests.get(vaa_url, timeout=timeout, verify=True)
            response.raise_for_status()
            data = response.json()

            vaa_id_list = pd.DataFrame(data["data"])
            if vaa_id_list.empty or "text_link" not in vaa_id_list.columns:
                return pd.DataFrame({"text_link": []})
            return vaa_id_list["text_link"].to_frame()
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warning(
                f"VAA list request failed on attempt {attempt}/{max_tries}: "
                f"{type(e).__name__}: {e}"
            )
            if attempt < max_tries:
                time.sleep(backoff)

    logger.error(f"Problem connecting to VAA API after {max_tries} attempts")
    return None


def fetch_vaa_page(url, max_tries=3, timeout=10, backoff=2):
    """Fetch a VAA text page, retrying on transient network errors.

    Returns the ``requests.Response`` on success, or ``None`` if every attempt
    failed (e.g. repeated read timeouts from the upstream server).
    """
    for attempt in range(1, max_tries + 1):
        try:
            return requests.get(url, timeout=timeout, verify=True)
        except requests.exceptions.RequestException as e:
            logger.warning(
                f"VAA page request failed on attempt {attempt}/{max_tries}: {e}"
            )
            if attempt < max_tries:
                time.sleep(backoff)
    logger.error(f"Giving up on VAA page after {max_tries} attempts: {url}")
    return None


VAA_FIELDS = [
    "DTG",
    "VAAC",
    "VOLCANO",
    "PSN",
    "AREA",
    "SUMMIT ELEV",
    "SOURCE ELEV",
    "ADVISORY NR",
    "INFO SOURCE",
    "AVIATION COLOR CODE",
    "ERUPTION DETAILS",
    "OBS VA DTG",
    "OBS VA CLD",
    "FCST VA CLD +6HR",
    "FCST VA CLD +12HR",
    "FCST VA CLD +18HR",
    "RMK",
    "NXT ADVISORY",
]


def parse_vaa_fields(text, fields=None):
    """Parse a VAA text product into a dict of field label -> value.

    Handles both advisory layouts: fields separated by blank lines, and fields
    on consecutive lines with no blank separators. Walks line by line, starting
    a new field on any known ``LABEL:`` and treating other non-blank lines as
    continuations. Newlines inside a value are preserved so polygon parsing can
    still split on them. ``"header"`` holds the lines before the first field.
    """
    if fields is None:
        fields = VAA_FIELDS

    # Longest label first so e.g. "OBS VA DTG" is preferred over "DTG".
    labels = sorted(fields, key=len, reverse=True)

    vaa = {}
    header_lines = []
    current = None

    for line in text.splitlines():
        stripped = line.strip()

        matched = None
        for label in labels:
            if stripped.startswith(label + ":"):
                matched = label
                break

        if matched is not None:
            current = matched
            vaa[current] = stripped[len(matched) + 1:].strip().rstrip("=").rstrip()
        elif not stripped:
            continue
        elif current is not None:
            vaa[current] = f"{vaa[current]}\n{stripped.rstrip('=').rstrip()}".strip("\n")
        else:
            header_lines.append(stripped)

    vaa["header"] = "\n".join(header_lines)
    return vaa


def parse_vaa_dtg(dtg):
    """Convert a VAA ``DTG`` string to a UTC timestamp.

    Advisories use either ``YYYYMMDD/HHMMZ`` or the abbreviated ``YYMMDD/HHMMZ``.
    """
    date_txt, _, time_txt = dtg.strip().rstrip("Z").partition("/")
    fmt = "%Y%m%d%H%M" if len(date_txt) == 8 else "%y%m%d%H%M"
    return pd.to_datetime(date_txt + time_txt, format=fmt, utc=True)


def process_vaa_id(vaa_id):

    page = fetch_vaa_page(vaa_id["text_link"])
    if page is None:
        return None

    vaa = parse_vaa_fields(page.text)

    if "TEST VAA" in vaa["header"]:
        return None

    # A malformed or truncated advisory (missing field -> KeyError, junk value
    # -> ValueError/IndexError) should skip that advisory, not kill the run.
    try:
        vaa["lat"], vaa["lon"] = text_to_latlon(vaa["PSN"])
        vaa["time"] = parse_vaa_dtg(vaa["DTG"])
        volcano = re.findall(r"\D+", vaa["VOLCANO"])[0]
    except (KeyError, ValueError, IndexError) as e:
        logger.warning(
            f"Skipping malformed VAA {vaa_id['text_link']}: {type(e).__name__}: {e}"
        )
        return None

    vaa["id"] = f"{vaa['DTG']}-{volcano.strip()}"

    return vaa


def process_polygons(vaa, field):
    lats = []
    lons = []
    flight_level_txt = ""

    if field not in vaa:
        return lons, lats, flight_level_txt

    if not isinstance(vaa[field], str):
        return lons, lats, flight_level_txt

    
    obs_text = vaa[field].replace("\n", " ")

    if "VA NOT IDENTIFIABLE " in obs_text:
        return lons, lats, flight_level_txt

    if "FL" in obs_text:
        lvl_pattern = re.compile(r".*\S+/FL\S+")
        time_and_level = lvl_pattern.findall(obs_text)
        if time_and_level:
            time_and_level = time_and_level[0]
        else:
            time_and_level = ""

        tmp_text = obs_text.replace(time_and_level, "")
        lat_lon_txt_pairs = tmp_text.split(" - ")

        for pr in lat_lon_txt_pairs:
            tmp_lat, tmp_lon = text_to_latlon(pr)
            lats.append(tmp_lat)
            lons.append(tmp_lon)

        if time_and_level:
            level = time_and_level.split(" ")[-1].split("/")
            flight_levels = np.array([])
            for fl in level:
                if fl == "SFC":
                    height = 0
                elif "FL" in fl:
                    height = float(fl.split("FL")[-1]) * 100
                else:
                    height = np.nan
                flight_levels = np.append(flight_levels, height)

        if np.nan not in flight_levels:
            flight_level_txt = f"{flight_levels[0]:,g} - {flight_levels[1]:,g} ft"

    return lons, lats, flight_level_txt


def text_to_latlon(latlon_txt):
    pr = latlon_txt.strip()
    pr = pr.replace('E','')
    pr = pr.replace('W','-')
    pr = pr.replace('N','')
    pr = pr.replace('S','-')
    pr = pr.split(' ')

    tmp_lat = pr[0]
    tmp_lon = pr[1]

    lat_sign =  np.sign(float(tmp_lat))
    lon_sign =  np.sign(float(tmp_lon))

    tmp_lat = float(tmp_lat[:-2]) + lat_sign*float(tmp_lat[-2:])/60
    tmp_lon = float(tmp_lon[:-2]) + lon_sign*float(tmp_lon[-2:])/60

    if tmp_lon > 0:
        tmp_lon -= 360

    return tmp_lat, tmp_lon


def get_extent(LONS, LATS):

    lat0 = np.mean([LATS.max(), LATS.min()])
    lon0 = np.mean([LONS.max(), LONS.min()])
    lat_dist = gps2dist_azimuth(LATS.min(), lon0, LATS.max(), lon0)[0] / 1000
    lon_dist = gps2dist_azimuth(lat0, LONS.min(), lat0, LONS.max())[0] / 1000

    dist = np.max([lat_dist, lon_dist])
    dist = np.round(1.5 * dist)

    dlat = dist / 111.1
    dlon = dlat / np.cos(lat0 * np.pi / 180)

    latmin = lat0 - dlat/2
    latmax = lat0 + dlat/2
    lonmin = lon0 - dlon/2
    lonmax = lon0 + dlon/2

    return [lonmin, lonmax, latmin, latmax]
