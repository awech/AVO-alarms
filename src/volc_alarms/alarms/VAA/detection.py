"""
Download and parsing routines for the VAA alarm.

Fetches the Mesonet VAA advisory list and individual text products, parses the
free-text advisory into structured fields, converts VAA coordinate strings to
latitude/longitude, extracts observed/forecast ash-cloud polygons, and
computes a map extent that frames them.
"""

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

    Parameters
    ----------
    T0 : obspy.UTCDateTime
        Date to query; only the calendar date is used.
    max_tries : int, optional
        Maximum number of attempts, by default 3.
    timeout : float, optional
        Per-request timeout in seconds, by default 10.
    backoff : float, optional
        Seconds to wait between attempts, by default 2.

    Returns
    -------
    pandas.DataFrame or None
        A single-column ``text_link`` DataFrame on success (which may be empty
        if there are no advisories for that date), or ``None`` if the API
        could not be reached or parsed after ``max_tries`` attempts.
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

    Parameters
    ----------
    url : str
        URL of the advisory text page to fetch.
    max_tries : int, optional
        Maximum number of attempts, by default 3.
    timeout : float, optional
        Per-request timeout in seconds, by default 10.
    backoff : float, optional
        Seconds to wait between attempts, by default 2.

    Returns
    -------
    requests.Response or None
        The response on success, or ``None`` if every attempt failed (e.g.
        repeated read timeouts from the upstream server).
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
    still split on them.

    Parameters
    ----------
    text : str
        Raw advisory text product.
    fields : list of str, optional
        Known field labels to recognize. Defaults to :data:`VAA_FIELDS` when
        ``None``.

    Returns
    -------
    dict
        Mapping of field label to its (possibly multi-line) value. The
        ``"header"`` key holds the lines before the first recognized field.
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

    Parameters
    ----------
    dtg : str
        The advisory ``DTG`` date-time group string.

    Returns
    -------
    pandas.Timestamp
        The parsed, timezone-aware (UTC) timestamp.
    """
    date_txt, _, time_txt = dtg.strip().rstrip("Z").partition("/")
    fmt = "%Y%m%d%H%M" if len(date_txt) == 8 else "%y%m%d%H%M"
    return pd.to_datetime(date_txt + time_txt, format=fmt, utc=True)


def process_vaa_id(vaa_id):
    """Download and parse a single VAA advisory into a record.

    Fetches the advisory text, parses its fields, skips test advisories, and
    derives latitude/longitude, time, and a unique id. Malformed or truncated
    advisories are skipped (logged) rather than raising.

    Parameters
    ----------
    vaa_id : pandas.Series or Mapping
        Row exposing ``text_link`` (the advisory URL).

    Returns
    -------
    dict or None
        The parsed advisory with added ``lat``, ``lon``, ``time``, and ``id``
        keys, or ``None`` if it is a test advisory, could not be downloaded,
        or was malformed.
    """
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
    """Parse a VAA cloud field into a list of per-sub-polygon groups.

    A field can carry MULTIPLE sub-polygons (each its own level + ring),
    separated by newlines. Forecast fields may lead with a ``DD/HHMM`` time
    token and trail each ring with a ``MOV <DIR> <N>KT`` motion token; a
    sub-polygon can also be ``NO VA EXP`` beside a real sibling ring.

    Parameters
    ----------
    vaa : dict
        Parsed advisory record (see :func:`parse_vaa_fields`).
    field : str
        Name of the cloud field to parse (e.g. ``"OBS VA CLD"`` or
        ``"FCST VA CLD +6HR"``).

    Returns
    -------
    list of tuple
        A list of ``(lons, lats, level_txt)`` tuples, one per parsed ring,
        where ``lons`` and ``lats`` are lists of floats and ``level_txt`` is a
        formatted flight-level string (possibly empty). Returns ``[]`` for a
        missing field, a non-string field, a ``VA NOT IDENTIFIABLE`` field, or
        a field with no real coordinate ring (e.g. a whole-field
        ``NO VA EXP``).
    """
    if field not in vaa:
        return []

    if not isinstance(vaa[field], str):
        return []

    # Normalize newlines to spaces first so wrapped coordinates join.
    obs_text = vaa[field].replace("\n", " ")

    if "VA NOT IDENTIFIABLE" in obs_text:
        return []

    # Recognize a level ONLY where a bound-pair is immediately followed by
    # whitespace and a coordinate token ([NS]\d). This skips the leading
    # DD/HHMM(Z) time token (followed by the level, not a coordinate) and any
    # digit runs inside coordinates.
    level_at = re.compile(r"(FL\d+|SFC|\d+)/(FL\d+|SFC|\d+)(?=\s+[NS]\d)")

    matches = list(level_at.finditer(obs_text))
    if not matches:
        # No real coordinate ring (e.g. whole-field "NO VA EXP").
        return []

    groups = []
    for i, m in enumerate(matches):
        lo_bound, hi_bound = m.group(1), m.group(2)

        # This segment's coordinate run spans from after the level token to the
        # next level token (or end of field).
        seg_start = m.end()
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(obs_text)
        coords = obs_text[seg_start:seg_end]

        # Strip a trailing MOV <DIR> <N>KT motion token before splitting.
        coords = re.sub(r"\s*MOV\s+\S+\s+\d+\s*KT.*$", "", coords).strip()

        # A sub-polygon with no coordinate token (e.g. "NO VA EXP"): skip it
        # without dropping sibling rings.
        if not re.search(r"[NS]\d", coords):
            continue

        lats = []
        lons = []
        for pr in coords.split(" - "):
            tmp_lat, tmp_lon = text_to_latlon(pr)
            lats.append(tmp_lat)
            lons.append(tmp_lon)

        flight_levels = np.array([])
        for fl in (lo_bound, hi_bound):
            if fl == "SFC":
                height = 0
            elif fl.startswith("FL"):
                height = float(fl[2:]) * 100
            elif fl.isdigit():
                height = float(fl) * 100
            else:
                height = np.nan
            flight_levels = np.append(flight_levels, height)

        level_txt = ""
        if flight_levels.size == 2 and not np.isnan(flight_levels).any():
            level_txt = f"{flight_levels[0]:,g} - {flight_levels[1]:,g} ft"

        groups.append((lons, lats, level_txt))

    return groups


def text_to_latlon(latlon_txt):
    """Convert a VAA coordinate string to decimal latitude/longitude.

    Parses the degrees-and-minutes format used in advisories (e.g.
    ``"N5612 W15430"``), applying hemisphere signs and normalizing longitude
    to the ``(-360, 0]`` range used elsewhere in the package.

    Parameters
    ----------
    latlon_txt : str
        A single whitespace-separated ``lat lon`` coordinate token.

    Returns
    -------
    tmp_lat : float
        Decimal latitude in degrees.
    tmp_lon : float
        Decimal longitude in degrees.
    """
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
    """Compute a map extent that frames a set of coordinates.

    Finds the bounding box of the given longitudes/latitudes, measures its
    width and height in km, and returns a square-ish extent padded to 1.5x the
    larger dimension and centered on the coordinates.

    Parameters
    ----------
    LONS : numpy.ndarray
        Longitudes in degrees.
    LATS : numpy.ndarray
        Latitudes in degrees.

    Returns
    -------
    list of float
        Map extent as ``[lonmin, lonmax, latmin, latmax]`` in degrees.
    """
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
