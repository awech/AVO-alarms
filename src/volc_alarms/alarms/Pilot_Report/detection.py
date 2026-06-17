import os
import re
import zipfile
from pathlib import Path

import pandas as pd
import requests
import shapefile
from shutil import rmtree

from volc_alarms.utils.setup_utils import get_logger, load_volcano_list, TMP_DIR

logger = get_logger(__name__)


def download_pilot_reports(T0, config):

    volcs = load_volcano_list()
    volcs = volcs[volcs["PIREP"] == "Y"]

    T2 = T0
    T1 = T2 - config.duration

    t1 = (
        f"&year1={T1.strftime('%Y')}"
        f"&month1={T1.strftime('%m')}"
        f"&day1={T1.strftime('%d')}"
        f"&hour1={T1.strftime('%H')}"
        f"&minute1={T1.strftime('%M')}"
    )
    t2 = (
        f"&year2={T2.strftime('%Y')}"
        f"&month2={T2.strftime('%m')}"
        f"&day2={T2.strftime('%d')}"
        f"&hour2={T2.strftime('%H')}"
        f"&minute2={T2.strftime('%M')}"
    )
    pirep_url = f"{os.getenv('PIREP_URL')}?fmt=shp{t1}{t2}"

    state = "OK"
    archive = None
    tmp_zipfile = TMP_DIR / "pireps.zip"
    try:
        with open(tmp_zipfile, "wb") as f:
            resp = requests.get(pirep_url, verify=False, timeout=10)
            f.write(resp.content)
    except Exception:
        logger.error("Request error from PIREP API")
        state = "WARNING"
        return state, archive

    if zipfile.is_zipfile(tmp_zipfile):
        archive = zipfile.ZipFile(tmp_zipfile, "r")
        logger.info("New pilot reports from API call")
    else:
        logger.info("No new pilot reports from API call")

    os.remove(tmp_zipfile)

    return state, archive


def pirep_archive_to_dataframe(T0, config, archive):

    T2 = T0
    T1 = T2 - config.duration

    tmp_zipped_dir = TMP_DIR / "tmp_zipped_dir"
    archive.extractall(path=tmp_zipped_dir)
    T1_str = T1.strftime('%Y%m%d%H%M')
    T2_str = T2.strftime('%Y%m%d%H%M')
    shp_path = tmp_zipped_dir / f"pireps_{T1_str}_{T2_str}"

    # read file, parse out the records
    sf = shapefile.Reader(shp_path)
    fields = [x[0] for x in sf.fields][1:]
    records = sf.records()

    # convert to a DataFrame
    pirep_df = pd.DataFrame(columns=fields, data=records)
    pirep_df['VALID'] = pd.to_datetime(pirep_df['VALID'])
    pirep_df = pirep_df[pirep_df.LAT > 49]
    pirep_df["time"] = pd.to_datetime(pirep_df["VALID"])
    pirep_df["lat"] = pirep_df["LAT"]
    pirep_df["lon"] = pirep_df["LON"]

    # delete duplicate events with different text versions in the 'REPORT' field'
    A = pirep_df.copy()
    del A['REPORT']
    A.drop_duplicates(inplace=True)
    pirep_df = pirep_df.loc[A.index]
    pirep_df.reset_index(drop=True, inplace=True)

    rmtree(tmp_zipped_dir)

    return pirep_df


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


def get_height_text(FL):
    try:
        height_text = f"Flight level: {FL:,.0f} feet asl"
    except Exception:
        logger.warning('Could not parse flight level from report')
        height_text = "Flight level: UNKNOWN"
    return height_text


def get_pilot_remark(report):

    pattern = re.compile(r'^(?:\s)?RM(.*)$')
    fields = report.split("/")

    pilot_remark = ""
    for f in fields:
        m = pattern.match(f)
        if m:
            pilot_remark = m.group(1)
            pilot_remark = pilot_remark.strip()
            pilot_remark = pilot_remark.capitalize()
            logger.info(f"Pilot remark: {pilot_remark}")

    if not pilot_remark:
        pilot_remark = "NA"
        logger.warning("Unable to extract pilot remarks")

    return pilot_remark
