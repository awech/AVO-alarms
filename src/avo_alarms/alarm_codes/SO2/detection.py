import os
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


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
            soup = None

    return table, soup


def get_so2_images(soup, config):
    base_url = "://".join(urlparse(os.environ["SACS_URL"])[:2])
    imgs = soup.find_all("img")
    img_files = []
    img_file_name = Path("tmp_files/sacs_out_.png")
    for im in imgs:
        if "/alert" in im.get("src"):
            img_files.append(urljoin(base_url, im.get("src")))

    for i, image in enumerate(img_files[:2]):
        r = requests.get(image, verify=False, timeout=10)
        if r.status_code == 200:
            with open(
                Path(str(img_file_name).replace(".png", str(i + 1) + ".gif")), "wb"
            ) as out:
                for bits in r.iter_content():
                    out.write(bits)

        gif = Path(str(img_file_name).replace(".png", str(i + 1) + ".gif"))
        from PIL import Image

        img = Image.open(gif)
        img.save(gif.with_suffix("png"), "png", optimize=True, quality=300)
        os.remove(gif)
