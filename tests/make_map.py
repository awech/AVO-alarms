import os
import sys
import time
from pathlib import Path

import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import pandas as pd


# get the script directory
script_dir = Path(os.path.dirname(__file__))

# set the current working directory to the script parent
# directory
os.chdir(script_dir.parent)
# add to path
sys.path.append(os.getcwd())

plt.style.use(Path("utils") / "alarms.mplstyle")
from utils import plotting


#########################################################
########## TESTING #######################################

start = time.time()

output_folder = Path("tests") / "outputs"

df = pd.read_excel(Path("alarm_aux_files") / "volcano_list.xlsx").set_index("Volcano")
volcano = "Spurr"


#########################################################
#########################################################


print("making basemap example")
fig, ax = plt.subplot_mosaic(
    [
        ["boring"],
        ["land"],
        ["hillshade"],
    ],
    figsize=(3, 10),
)

for a in ax:
    ax[a] = plotting.make_map(
        df.loc[volcano, "Latitude"],
        df.loc[volcano, "Longitude"],
        xdist=2000,
        ydist=2000,
        ax=ax[a],
        basemap=a,
        projection="mercator",
    )
    ax[a].set_title(f"basemap = '{a}'", fontsize=10)


print("saving basemap example")
plt.savefig(output_folder / "avo-alarms_map-basemap_example.png")


######################################################################
######################################################################


print("making projection example")

fig, ax = plt.subplot_mosaic(
    [
        ["mercator"],
        ["orthographic"],
        ["albers"],
        ["nearside"],
    ],
    figsize=(3, 12),
)

for a in ax:
    ax[a] = plotting.make_map(
        df.loc[volcano, "Latitude"],
        df.loc[volcano, "Longitude"],
        xdist=2000,
        ydist=2000,
        ax=ax[a],
        basemap="boring",
        projection=a,
    )
    ax[a].set_title(f"projection = '{a}'", fontsize=10)

print("saving projection example")
plt.savefig(output_folder / "avo-alarms_map-projection_example.png")

######################################################################
#######################################################################


print("making template example")

fig, ax = plt.subplots(figsize=(6, 6))

# SET MAP EXTENT AND VOLCANO LAT LON
dist = 25

volc_lat = df.loc[volcano, "Latitude"]
volc_lon = df.loc[volcano, "Longitude"]


# NORMAL MAP
ax = plotting.make_map(
    volc_lat,
    volc_lon,
    xdist=dist,
    ydist=dist,
    ax=ax,
    basemap="hillshade",
)

extent = plotting.get_extent(volc_lat, volc_lon, xdist=dist, ydist=dist)

label_kwargs = (
    {
        "direction_label": True,
        "number_format": ".2f",
    }
)

plotting.map_ticks(
    ax,
    extent,
    nticks_x=2,
    nticks_y=2,
    grid_kwargs={"lw": 0.2, "ls": "--"},
    lon_fmt_kwargs=label_kwargs,
    lat_fmt_kwargs=label_kwargs,
    y_rotate=90,
    ticks_right=True,
)
ax.set_title("Alarms general template")

# MAKE THE INSET
ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
ax_inset = plotting.make_map(
    volc_lat,
    volc_lon,
    xdist=500,
    ydist=300,
    ax=ax_inset,
    basemap="land",
    projection="orthographic",
)

# INSET BOUNDING BOX
plotting.add_inset_polygon(
        ax_inset, extent, facecolor="none", edgecolor="red", linewidth=0.35
    )
# rivers for reference in case it's just a gray blob
ax_inset.add_feature(cfeature.RIVERS, linewidth=0.5, linestyle=":")

print("saving template example")
plt.savefig(output_folder / "avo-alarms_map-general_example.png")
end = time.time()
print(f"DONE in {end - start:.2f} seconds")