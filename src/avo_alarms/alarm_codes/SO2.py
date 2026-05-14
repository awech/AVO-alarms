import os
import requests
import pandas as pd
from obspy import UTCDateTime
from urllib.parse import urlparse, urljoin
import matplotlib as m
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import traceback
import re

from avo_alarms.utils import messaging, plotting, processing, downloading, alarming
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)


def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True, force_flag=False):

    T0_str = T0.strftime('%Y-%m-%d %H:%M')
    table, soup = downloading.download_SO2()

    if table is None:
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    try:
        table = table.get_text().split('\n')
        table = table[1:-1]

        date = table[1].split(":")[-1].replace(" ", "")
        time = table[2].split(" :")[-1].split("UTC")[0].replace(" ", "")

        lat_str = table[4].split(":")[-1]
        lon_str = table[3].split(":")[-1]
        lat, lat_dir = re.findall(r"(\d+\.\d+)\s{1}(\S{1})", lat_str)[0]
        lon, lon_dir = re.findall(r"(\d+\.\d+)\s{1}(\S{1})", lon_str)[0]
        lat = float(lat)
        lon = float(lon)
        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon

        volcs = load_volcano_list()
        volcs = volcs[volcs["SO2"] == "Y"]
        volcs = processing.volcano_distance(lon, lat, volcs)
        volcs = volcs.sort_values("distance")


        # lon    = float(table[3].split(':')[-1].split('deg')[0].replace(' ',''))
        # lat    = float(table[4].split(':')[-1].split('deg')[0].replace(' ',''))
        # SZA    = table[4].split(':')[-1].split('deg')[0].replace(' ','')
        # SO2max = table[5].split(':')[-1].split('DU')[0].replace(' ','')
        # S02ht  = table[6].split(':')[-1].split('km')[0].replace(' ','')
    except Exception:
        logger.warning("Page error.")
        state = "WARNING"
        state_message = f"{T0_str} (UTC) webpage error"
        messaging.icinga(config, state, state_message, send=icinga_flag)	
        return	


    volcano_name = volcs.iloc[0].Volcano
    alert_time = UTCDateTime(date + time).strftime("%Y-%m-%d %H:%M:%S")
    event_id = f"{volcano_name} - {alert_time}"
    new_alert = alarming.already_processed(config, event_id, test=test_flag)

    if new_alert and volcs.distance.min() < config.max_distance:

        logger.info(f"....New detection at {volcano_name}....")

        logger.info("Downloading image")
        try:
            get_so2_images(soup, config)
        except Exception:
            logger.warning("Problem downloading images.")

        logger.info("Trying to make figure attachment")
        try:
            filename = plot_fig(config)
            logger.info("Figure generated successfully")
        except Exception:
            filename = []
            logger.error("Problem making figure. Continue anyway")
            b = traceback.format_exc()
            err_message = "".join(f"{a}\n" for a in b.splitlines())
            logger.error(err_message)
            pass

        
        logger.info("Drafting alert")
        subject, message = create_message(date, alert_time, table, config, volcs)

        # logger.info("Sending direct alert")
        # messaging.send_alert(
        #     config.alarm_name, subject, message, attachment=filename, test=test_flag
        # )


        logger.info("Posting to Mattermost")
        messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)
        alarming.record_send(config, T0, volcano=volcano_name, event_id=event_id, test=test_flag)

        # delete the file you just sent
        if filename:
            os.remove(filename)

        state_message = f"{T0_str} (UTC) SO2 detection!"
        state = "CRITICAL"
    elif volcs.distance.min() < config.max_distance and not new_alert:
        state_message = f"{T0_str} (UTC) Old SO2 detection! [{alert_time}]"
        state = "WARNING"
    else:
        state_message = f"{T0_str} (UTC) No new SO2 detections"
        state = "OK"

    # send heartbeat status message to icinga
    messaging.icinga(config, state, state_message, send=icinga_flag)




def get_so2_images(soup, config):
    base_url = "://".join(urlparse(os.environ["SACS_URL"])[:2])
    imgs = soup.find_all("img")
    img_files = []
    for im in imgs:
        if "/alert" in im.get("src"):
            img_files.append(urljoin(base_url, im.get("src")))

    for i, image in enumerate(img_files[:2]):
        r = requests.get(image, verify=False, timeout=10)
        if r.status_code == 200:
            with open(
                config.img_file.replace(".png", str(i + 1) + ".gif"), "wb"
            ) as out:
                for bits in r.iter_content():
                    out.write(bits)

        gif = config.img_file.replace(".png", str(i + 1) + ".gif")
        from PIL import Image

        img = Image.open(gif)
        img.save(gif.replace("gif", "png"), "png", optimize=True, quality=300)
        os.remove(gif)


def plot_fig(config):

    plt.figure(figsize=(3, 4.4))

    tmp_file1 = config.img_file.replace(".png", "1.png")
    tmp_file2 = config.img_file.replace(".png", "2.png")
    img1 = mpimg.imread(tmp_file1)
    img2 = mpimg.imread(tmp_file2)

    plt.subplot(2, 1, 1)
    plt.imshow(img1)
    plt.gca().set_xticks([])
    plt.gca().set_yticks([])

    plt.subplot(2, 1, 2)
    plt.imshow(img2)
    plt.gca().set_xticks([])
    plt.gca().set_yticks([])

    plt.tight_layout(pad=0.5)

    jpg_file = plotting.save_file(plt, config, dpi=500)

    os.remove(tmp_file1)
    os.remove(tmp_file2)

    return jpg_file



def create_message(date, time, table, config, volcs):

    subject = "SO2 detection"

    message = f"{messaging.format_timestring(UTCDateTime(time))}"

    message += "\n".join(table[2:])
    # message = message.replace('     ',' ')
    # message = message.replace('   ',' ')
    # message = message.replace('  ',' ')
    message = message.replace(" deg.", "")

    v_text = ""
    for i, row in volcs.sort_values("distance")[:3].iterrows():
        v_text = f"{v_text}{row.Volcano} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}\n\nNearest volcanoes: {v_text[:-2]}\n"
    message += f"\n{os.environ['SACS_URL']}"

    return subject, message