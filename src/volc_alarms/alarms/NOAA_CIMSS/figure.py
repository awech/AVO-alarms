import os
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from volc_alarms.utils import plotting
from volc_alarms.utils.setup_utils import get_logger, TMP_DIR

logger = get_logger(__name__)


def plot_fig(alert, config, test=False):

    fig, ax = plt.subplot_mosaic(
        [["img1"], ["img2"], ["map"]],
        figsize=(3, 6.6),
        height_ratios=[1.1, 1.1, 1]
    )

    title_str = (
        f"{str(alert.object_date_time)} UTC\n"
        f"{alert.alert_header.capitalize()}\n"
        f"Method: {alert.method}"
    )
    ax["img1"].set_title(title_str, fontsize=8)
    
    # read in images downloaded from NOAA/CIMSS webpage
    img_file = TMP_DIR / "noaa_out_.png"
    tmp_file1 = Path(str(img_file).replace(".png", "1.png"))
    tmp_file2 = Path(str(img_file).replace(".png", "2.png"))
    img1 = mpimg.imread(tmp_file1)
    img2 = mpimg.imread(tmp_file2)

    ax["img1"].imshow(img1)
    ax["img1"].set_xticks([])
    ax["img1"].set_yticks([])

    ax["img2"].imshow(img2)
    ax["img2"].set_xticks([])
    ax["img2"].set_yticks([])


    X_DIST = getattr(config, "map_xdist", 150)
    Y_DIST = getattr(config, "map_ydist", 150)
    ax["map"], extent = plotting.make_map(
        ax["map"],
        alert.lat_rc,
        alert.lon_rc,
        basemap="HIGHRES",
        xdist=X_DIST,
        ydist=Y_DIST,
    )

    plotting.map_ticks(ax["map"], extent, grid_kwargs="default")
    plotting.add_volcanoes_to_map(ax["map"], extent, config, linewidths=0.1)
    plotting.add_scale_bar(ax["map"], 25, txt_yoffset=0.02, extent=extent)

    # draw rectangle on inset map
    ax_inset = fig.add_axes([0.66, 0.25, 0.15, 0.15])
    ax_inset, inset_extent = plotting.make_map(ax_inset, alert.lat_rc, alert.lon_rc,
                                    xdist=400,
                                    ydist=300,
                                    basemap="land",
                                    projection="orthographic")
    plotting.add_inset_polygon(ax_inset, extent)
    fig.subplots_adjust(hspace=0.1)
    jpg_file = plotting.save_file(fig, config, test=test, dpi=500)

    # remove images downloaded from NOAA/CIMSS webpage
    os.remove(tmp_file1)
    os.remove(tmp_file2)

    return jpg_file
