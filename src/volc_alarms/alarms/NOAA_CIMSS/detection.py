import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests
import urllib3
from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from volc_alarms.utils.setup_utils import TMP_DIR, get_logger, load_volcano_list

urllib3.disable_warnings()

logger = get_logger(__name__)

# Maps an alert's ``alert_type`` to the volcano-list column that governs whether
# that alert type should be suppressed for a given volcano.
ALERT_TYPE_COLUMNS = {"ash": "NOAA Ash", "hot": "NOAA Thermal", "ice": "NOAA Ice"}


def resolve_ignore_column(alert_type, volcs_columns):
    """Return the volcano-list column that governs this alert type.

    Prefers the granular per-type column (e.g. ``"NOAA Ash"``) when present,
    otherwise falls back to the generic ``"NOAA"`` column. Returns ``None`` when
    no relevant column exists, meaning no volcanoes should be filtered.

    Parameters
    ----------
    alert_type : str
        The alert's ``alert_type`` (e.g. ``"ash"``, ``"hot"``, ``"ice"``).
    volcs_columns : Iterable[str]
        Columns available in the volcano list.

    Returns
    -------
    str or None
        The column name to filter on, or ``None`` if none applies.
    """
    specific_col = ALERT_TYPE_COLUMNS.get(alert_type)
    if specific_col and specific_col in volcs_columns:
        return specific_col
    if "NOAA" in volcs_columns:
        return "NOAA"
    return None


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


def scrape_cimss_alert(alert):
    from bs4 import BeautifulSoup

    attempt = 1
    max_tries = 3

    while attempt <= max_tries:
        try:
            soup = BeautifulSoup(
                requests.get(alert.alert_url, verify=True, timeout=10).content
            )
            redir = soup.select_one("#loginform-custom")["action"]

            # This URL will be the URL that your login form points to with the "action" tag.
            POST_LOGIN_URL = redir
            # This URL is the page you actually want to pull down with requests.
            REQUEST_URL = alert.alert_url

            payload = {"log": os.environ["CIMSS_USERNAME"], "pwd": os.environ["CIMSS_PASSWORD"]}

            with requests.Session() as session:
                session.post(POST_LOGIN_URL, data=payload, verify=True, timeout=10)
                r = session.get(REQUEST_URL, verify=True, timeout=10)
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
    img_file = TMP_DIR / "noaa_out_.png"
    for i, img in enumerate(image_files):
        img.get("src")
        im_url = urljoin(base_url, img.get("src"))
        r = requests.get(im_url, verify=True, timeout=10)

        if r.status_code == 200:
            new_file = Path(str(img_file).replace(".png", f"{i+1:g}.png"))
            with open(new_file, "wb") as out:
                for bits in r.iter_content():
                    out.write(bits)


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


def check_ignore_volcano(cimss_df):

    volcs = load_volcano_list().set_index("Name")

    cimss_df["keep"] = True

    for i, row in cimss_df.iterrows():
        if row.v_name not in volcs.index:
            continue

        col = resolve_ignore_column(row.alert_type, volcs.columns)
        if col is None:
            break  # no relevant column exists, keep all

        if volcs.loc[row.v_name, col] == "N":
            logger.info(f"{row.v_name} has '{col}' set to 'N'")
            cimss_df.loc[i, "keep"] = False

    return cimss_df


def process_alert_soup(soup, alert, config):

    output = {}
    try:
        output["instrument"] = get_instrument(soup)
        sections = soup.select("div[class*=alert_box]")
    except Exception as e:
        logger.error("Error processing NOAA CIMSS alert page")
        logger.error(e)
        return alert, None

    for soupy in sections:
        t = get_timestamp(soupy)
        lat_web, lon_web = get_latitude(soupy)
        if t:
            if (
                utc(alert.object_date_time) - utc(t)
            ) == 0 & (
                gps2dist_azimuth(
                    lat_web, lon_web, alert.lat_rc, alert.lon_rc
                )[0]
                / 1000
                == 0
            ):

                output["height_txt"] = get_height_txt(soupy)
                output["status_txt"] = get_alert_status_txt(soupy)
                output["type_txt"] = get_type_txt(soupy)

                get_cimss_image(soupy, alert, config)

                tmp_text = soupy.select("a[href*=individual]")
                aid = np.unique(
                    [
                        x["href"].split("#")[0].split("/")[-1]
                        for x in tmp_text
                    ]
                )
                alert["aid"] = aid

                break
    return alert, output


def get_instrument(soup):

    tbl = soup.find("div", {"class": "alert_box alert_report_summary"})
    rows = tbl.find_all("tr")
    row = [tr for tr in rows if "Primary" in str(tr)]
    instrument = row[0].find("td").text

    return instrument


def get_height_txt(soup):

    height_txt = soup.find(text=re.compile("Maximum Height [AMSL]"))
    if height_txt:
        height_txt += ":  " + height_txt.find_all_next("td")[0].text

    return height_txt


def get_alert_status_txt(soup):

    status_txt = soup.find(text=re.compile("Alert Status"))
    if status_txt:
        status_txt += ":  " + status_txt.find_all_next("td")[0].text

    return status_txt


def get_type_txt(soup):

    type_txt = soup.find(text=re.compile("Type of Volcanic Event"))
    if type_txt:
        type_txt += ":  " + type_txt.find_all_next("td")[0].text

    return type_txt


def get_timestamp(soup):

    time_txt = soup.find(text=re.compile("Date/Time"))
    if time_txt:
        time_txt = time_txt.find_all_next("td")[0].text.split("UTC")[0]

    return time_txt


def get_latitude(soup):

    lat_txt = soup.find(text=re.compile("Radiative Center"))
    lat = None
    lon = None
    if lat_txt:
        lat_txt = lat_txt.find_all_next("td")[0]
        lat, lon = re.findall(r"[-+]?(?:\d*\.*\d+)", lat_txt.text)
        lat = float(lat)
        lon = float(lon)

    return lat, lon
