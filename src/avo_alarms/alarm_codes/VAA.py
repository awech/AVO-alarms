import os
import re
import traceback
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from cartopy import crs as ccrs
from obspy import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth

from avo_alarms.utils import downloading, messaging, plotting, processing
from avo_alarms.utils.setup_utils import get_logger

warnings.filterwarnings("ignore")

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    logger.info(T0)
    T0_str = T0.strftime("%Y-%m-%d %H:%M")
    outfile_cols = ["time", "id"]

    if force_flag:
        T0 = UTCDateTime("2026-03-09 17:05")

    # download yesterday & today (mesonet api uses calendar date queries)
    vaa_id_list_1 = downloading.download_mesonet_vaa_list(T0 - 86400)
    vaa_id_list_2 = downloading.download_mesonet_vaa_list(T0)
    if vaa_id_list_1 is not None and vaa_id_list_2 is not None:
        vaa_id_list = pd.concat([vaa_id_list_1, vaa_id_list_2])
    else:
        vaa_id_list = None

    if vaa_id_list is None:
        logger.warning("Page error.")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    vaas_found = []
    for i, vaa_id in vaa_id_list.iterrows():
        vaa = process_vaa_id(vaa_id)
        vaas_found.append(vaa)
    vaas_df = pd.DataFrame(vaas_found)

    if "time" in vaas_df.columns:
        T1 = T0 - config.duration
        T1 = pd.to_datetime(T1.datetime).tz_localize("UTC")
        T2 = pd.to_datetime(T0.datetime).tz_localize("UTC")
        vaas_df = vaas_df[vaas_df["time"] >= T1]
        vaas_df = vaas_df[vaas_df["time"] <= T2]


    if len(vaas_df) == 0:
        state = "OK"
        state_message = f"{T0_str} (UTC) No new VAAs"
        processing.write_to_csv(vaas_df, config, outfile_cols)
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return

    vaas_df = vaas_df.sort_values("time")
    vaas_df = vaas_df.drop_duplicates(subset="id")
    new_vaas_df, vaas_df = processing.compare_to_old_events(vaas_df, config.outfile, outfile_cols)
    
    for i, row in new_vaas_df.iterrows():
        logger.info("New VAA detected")

        try:
            filename = make_map(row, config, test=test_flag)
        except Exception as e:
            ## TODO filename still hase "SIGMET" in it
            filename = []
            logger.error("Problem making figure. Continue anyway")
            logger.error(e)
            logger.error(traceback.format_exc())
            
        subject, message = create_message(row)

        if force_flag:
            logger.info("Sending message...")
            messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

        logger.info("Checking mattermost send...")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)

        # delete the file you just sent
        if filename:
            os.remove(filename)

        state = "CRITICAL"
        state_message = f"{T0.strftime('%Y-%m-%d %H:%M')} (UTC) New {subject}"
        
        messaging.icinga(config, state, state_message, send=icinga_flag)

    if not force_flag:
        processing.write_to_csv(vaas_df, config, columns=outfile_cols)
        


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


def process_vaa_id(vaa_id):

    page = requests.get(vaa_id["text_link"], timeout=10, verify=False)
    vaa_info = page.text.split("\n\n")

    vaa = dict()

    rows = [
        "DTG",
        "VAAC",
        "VOLCANO",
        "PSN",
        "AREA",
        "SUMMIT ELEV",
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
        "id",
        "time",
    ]

    vaa["header"] = vaa_info[0]

    for row in rows:
        for line in vaa_info:
            if row + ":" in line and "VA " + row + ":" not in line:
                line_txt = line.split(": ")[-1].replace("\n\n", " ")
                line_txt = line_txt.replace("=\n", "")
                vaa[row] = line_txt

    vaa["time"] = pd.to_datetime(vaa["DTG"])

    volcano = re.findall(r"\D+", vaa["VOLCANO"])[0]
    vaa["id"] = f"{vaa['DTG']}-{volcano.strip()}"

    return vaa


def make_map(vaa, config, test=False):

    lons_0, lats_0, level_0 = process_polygons(vaa, "OBS VA CLD")
    lons_6, lats_6, level_6 = process_polygons(vaa, "FCST VA CLD +6HR")
    lons_12, lats_12, level_12 = process_polygons(vaa, "FCST VA CLD +12HR")
    lons_18, lats_18, level_18 = process_polygons(vaa, "FCST VA CLD +18HR")

    LONS = np.concatenate((lons_0, lons_6, lons_12, lons_18))
    LATS = np.concatenate((lats_0, lats_6, lats_12, lats_18))
    LEVELS = np.array([level_0, level_6, level_12, level_18])

    n_levels = len(np.unique(LEVELS[LEVELS != ""]))

    if len(LONS) == 0 or len(LATS) == 0:
        logger.warning("No polygons to plot. Not generating figure.")
        return []

    v_lat, v_lon = text_to_latlon(vaa['PSN'])
    LONS = np.append(LONS, v_lon)
    LATS = np.append(LATS, v_lat)
    extent = get_extent(LONS, LATS)

    fig, ax = plt.subplots(figsize=(3.5, 3.5), layout="constrained")

    ax, extent = plotting.make_map(
        ax, v_lat, v_lon, basemap="land", extent=extent, projection="orthographic"
    )
    ax.coastlines(lw=0.2)

    plotting.map_ticks(ax, extent, grid_kwargs="default")
    ax.plot(v_lon, v_lat, "^", mfc="k", mec="w", ms=6, transform=ccrs.Geodetic())

    t_form = ccrs.PlateCarree()
    if lons_0:
        lvl_txt = f"\n({level_0:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_0, lats_0, '-', c='firebrick', lw=1.5, label=f'Observed{lvl_txt}', transform=t_form, zorder=100)
    if lons_6:
        lvl_txt = f"\n({level_6:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_6, lats_6, '--', c='orangered', lw=1.25, label='6H Forecast', transform=t_form, zorder=99)
    if lons_12:
        lvl_txt = f"\n({level_12:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_12, lats_12, '--', c='orange', lw=1, label='12H Forecast', transform=t_form, zorder=98)
    if lons_18:
        lvl_txt = f"\n({level_18:,g} asl)" if n_levels > 1 else ""
        ax.plot(lons_18, lats_18, '-.', c='goldenrod', lw=0.75, label='18H Forecast', transform=t_form, zorder=97)


    ax.legend(fontsize=6, loc='lower left')

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    vaa_time = UTCDateTime(vaa["DTG"]).strftime("%Y-%m-%d %H:%M")

    ax.set_title(
        f"{volcano_name} VAA\n{level_0}\n{vaa_time}", fontsize=10
    )
    plt.tight_layout()

    logger.info("Saving figure...")
    jpg_file = plotting.save_file(fig, config, dpi=300, test=test)
    plt.close(fig)

    return jpg_file


def create_message(vaa):

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    subject = f'{volcano_name} Volcanic Ash Advisory'

    t = UTCDateTime(vaa["DTG"])
    time_txt = messaging.format_timestring(t)

    try:
        lons_0, lats_0, level_0 = process_polygons(vaa, "OBS VA CLD")
        message = f"VAA {level_0}\n{time_txt}\n\n#### *Original Message*\n"
    except Exception as e:
        logger.warning("Error generating message contents")
        logger.error(e)
        message = f"Volcanic Ash Advisory\n{time_txt}\n\n#### *Original Message*\n"
    
    for key in vaa.keys():
        if key not in ["header", "id", "time"]:
            if isinstance(vaa[key], str):
                key_str = vaa[key].replace('\n', ' ')
                message += f"**{key}:** {key_str}\n"

    message = message.replace("\r\n", " ")

    return subject, message

