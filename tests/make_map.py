import os
import sys
import time
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import shapely.geometry as sgeom
from cartopy.io.img_tiles import GoogleTiles

# get the script directory
script_dir = Path(os.path.dirname(__file__))

# set the current working directory to the script parent
# directory
os.chdir(script_dir.parent)
# add to path
sys.path.append(os.getcwd())

plt.style.use(Path("utils") / "alarms.mplstyle")


class ShadedReliefESRI(GoogleTiles):
    # shaded relief
    def _image_url(self, tile):
        x, y, z = tile
        url = (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}.jpg"
        ).format(z=z, y=y, x=x)
        return url


def add_circle_boundary(ax):
    # Compute a circle in axes coordinates, which we can use as a boundary
    # for the map. We can pan/zoom as much as we like - the boundary will be
    # permanently circular.
    theta = np.linspace(0, 2 * np.pi, 100)
    center, radius = [0.5, 0.5], 0.5
    verts = np.vstack([np.sin(theta), np.cos(theta)]).T
    circle = mpath.Path(verts * radius + center)
    ax.set_boundary(circle, transform=ax.transAxes)


def create_bounding_box(lat, lon, ydist, xdist):
    """
    create a bounding box around a point on the earth
    with user specified horizontal and vertical distance



    Parameters
    ----------
    lat : float
        latitude of box center
    lon : float
        longitude of box center
    xdist : float
        horizontal distance from the center of box to the edge
    ydist : float
        vertical distance from the center of the box to the edge


    Return

    d_deg_lat : float
        degrees from lat to bounding box edge
    d_deg_lon : float
        degrees from lon to bounding box edge

    """

    a = 6378.1370
    b = 6356.7523

    e = (a**2 - b**2) / a**2
    # km per degree of longitude
    d_km_lon = (np.pi * a * np.cos(np.deg2rad(lon))) / (
        180 * np.sqrt(1 - e**2 * np.sin(np.deg2rad(lon)) ** 2)
    )
    # km per degree of latitude
    d_km_lat = (np.pi * a * (1 - e**2)) / (
        180 * (1 - e**2 * np.sin(np.deg2rad(lat)) ** 2) ** 1.5
    )

    # degrees needed to move to move the xdist
    d_deg_lon = xdist / d_km_lon

    # degrees neeeded to move to move the ydist
    d_deg_lat = ydist / d_km_lat

    return d_deg_lat, d_deg_lon


def make_path(extent):
    """_summary_

    Parameters
    ----------
    extent : _type_
        _description_
    """
    n = 20
    aoi = mpath.Path(
        list(zip(np.linspace(extent[0], extent[1], n), np.full(n, extent[3])))
        + list(zip(np.full(n, extent[1]), np.linspace(extent[3], extent[2], n)))
        + list(zip(np.linspace(extent[1], extent[0], n), np.full(n, extent[2])))
        + list(zip(np.full(n, extent[0]), np.linspace(extent[2], extent[3], n)))
    )

    return aoi


def make_map(
    volc_lat,
    volc_lon,
    ax,
    x_dist=25,
    y_dist=None,
    basemap="hillshade",
    projection="mercator",
    land_color="#80808050",
):

    # type checking the ax argument
    assert isinstance(ax, plt.Axes), "ax is not a matplotlib axis, make sure it is"

    # force either mercator or albers for projections
    # should take care of the main and inset axes situations
    projection = projection.upper()
    possible_projections = ["MERCATOR", "ALBERS", "ORTHOGRAPHIC", "NEARSIDE"]

    assert (
        projection in possible_projections
    ), f"{projection} not in possible projections. please choose mercator or albers"

    basemap = basemap.upper()

    possible_basemaps = ["BORING", "HILLSHADE", "LAND"]
    assert (
        basemap in possible_basemaps
    ), f"{basemap} not in possible basemaps. please choose boring or hillshade"

    # km to degrees conversion for bounding delta degrees from center
    # uneven distances so that figure is square with mercator projection
    if y_dist is None:
        y_dist = x_dist / 1.5
    d_deg_lat, d_deg_lon = create_bounding_box(
        lat=volc_lat, lon=volc_lon, xdist=x_dist, ydist=y_dist
    )
    # get bounding box lat and lon bounds
    #
    latitude_min, latitude_max = volc_lat - d_deg_lat, volc_lat + d_deg_lat
    longitude_min, longitude_max = volc_lon - d_deg_lon, volc_lon + d_deg_lon

    # bounding box extent in cartopy argument format
    extent = [longitude_min, longitude_max, latitude_min, latitude_max]

    # how detailed to make the hillshade scales to how
    # big of an area to map

    if x_dist <= 50:
        zoom_level = 13
    elif (x_dist > 50) & (x_dist <= 100):
        zoom_level = 11
    elif (x_dist > 100) & (x_dist < 500):
        zoom_level = 9
    else:
        zoom_level = 7

    if basemap == "HILLSHADE":
        projection = "MERCATOR"

    # set projection
    if projection == "MERCATOR":
        crs = ccrs.Mercator(central_longitude=volc_lon)

    elif projection == "ALBERS":
        crs = ccrs.AlbersEqualArea(
            central_longitude=volc_lon,
            central_latitude=volc_lat,
        )

    elif projection == "ORTHOGRAPHIC":
        crs = ccrs.Orthographic(
            central_longitude=volc_lon,
            central_latitude=volc_lat,
        )

    elif projection == "NEARSIDE":
        crs = ccrs.NearsidePerspective(
            central_longitude=volc_lon,
            central_latitude=volc_lat,
        )

    # get axis position and label
    ax_position = ax.get_position()
    ax_label = ax.get_label()

    # remove old "regular" axis and replace with geo axis
    fig = plt.gcf()
    ax.remove()
    ax = fig.add_axes(rect=ax_position, projection=crs, label=ax_label)

    # add the basemap
    if basemap == "HILLSHADE":
        ax.add_image(
            ShadedReliefESRI(),
            zoom_level,
            alpha=0.8,
        )

    elif basemap == "BORING":
        # add land and ocean features
        ax.add_feature(cfeature.STATES, lw=0.5)

    elif basemap == "LAND":
        ax.add_feature(cfeature.LAND, facecolor=land_color)

    ax.set_extent(extent, crs=ccrs.Geodetic())  # defaults to geodetic version of crs
    # cant use set_boundary on mercator for some reason.
    if projection != "MERCATOR":
        ax.set_boundary(make_path(extent), transform=ccrs.Geodetic())

    return ax


def add_map_grid(volc_lat, volc_lon, ax, x_dist=25, y_dist=None, fontsize=6):
    """_summary_

    Parameters
    ----------
    volc_lat : _type_
        _description_
    volc_lon : _type_
        _description_
    ax : _type_
        _description_
    fontsize : int, optional
        _description_, by default 6

    Returns
    -------
    _type_
        _description_
    """
    # GRIDLINES FOR MAIN MAP
    # format the grid lines
    gl = ax.gridlines(
        crs=ccrs.PlateCarree(),
        draw_labels=True,
        linewidth=0.25,
        linestyle="--",
        color="#808080",
        formatter_kwargs={
            "direction_label": True,
            "number_format": ".2f",
        },
    )

    if y_dist is None:
        y_dist = x_dist / 1.5

    d_lat, d_lon = create_bounding_box(
        lat=volc_lat, lon=volc_lon, xdist=x_dist, ydist=y_dist
    )

    # grid lines - taking care of being on either side of the
    # anti-meridian
    lon_line_locs = [volc_lon - (d_lon / 2), volc_lon + (d_lon / 2)]
    new_lon_locs = []
    for loc in lon_line_locs:
        if loc < -180:
            new_lon_locs.append(loc + 360)
        else:
            new_lon_locs.append(loc)

    new_lon_locs = np.array(new_lon_locs)
    new_lon_locs[new_lon_locs > 180] = new_lon_locs[new_lon_locs > 180] - 360

    gl.ylocator = mticker.FixedLocator([volc_lat - (d_lat / 2), volc_lat + (d_lat / 2)])
    # these aren't working with stuff that straddles the anti-meridian
    gl.xlocator = mticker.FixedLocator(new_lon_locs)
    gl.xlabel_style = {"fontsize": fontsize}
    gl.ylabel_style = {"fontsize": fontsize}
    gl.top_labels = False
    gl.left_labels = False
    gl.bottom_labels = True
    gl.right_labels = True

    return gl


#########################################################
########## TESTING #######################################
start = time.time()

output_folder = Path("tests") / "outputs"

df = pd.read_excel(Path("alarm_aux_files") / "volcano_list.xlsx").set_index("Volcano")
volcano = "Spurr"

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
    ax[a] = make_map(
        df.loc[volcano, "Latitude"],
        df.loc[volcano, "Longitude"],
        x_dist=2000,
        ax=ax[a],
        basemap=a,
        projection="mercator",
        # ticklabels=True,
    )
    ax[a].set_title(f"basemap = '{a}'", fontsize=10)


print("saving basemap example")
plt.savefig(output_folder / "avo-alarms_map-basemap_example.png")
######################################################################
print("making projection example")

fig, ax = plt.subplot_mosaic(
    [
        ["mercator"],
        ["orthographic"],
        ["albers"],
    ],
    figsize=(3, 10),
)

for a in ax:
    ax[a] = make_map(
        df.loc[volcano, "Latitude"],
        df.loc[volcano, "Longitude"],
        x_dist=2000,
        ax=ax[a],
        basemap="boring",
        projection=a,
        # ticklabels=True,
    )
    ax[a].set_title(f"projection = '{a}'", fontsize=10)

print("saving projection example")
plt.savefig(output_folder / "avo-alarms_map-projection_example.png")
#######################################################################
print("making template example")

fig, ax = plt.subplots(figsize=(6, 6))

# SET MAP EXTENT AND VOLCANO LAT LON
xdist = 25
ydist = xdist / 1.5

volc_lat = df.loc[volcano, "Latitude"]
volc_lon = df.loc[volcano, "Longitude"]


# NORMAL MAP
ax = make_map(
    volc_lat,
    volc_lon,
    x_dist=xdist,
    ax=ax,
    basemap="hillshade",
)
gl = add_map_grid(volc_lat, volc_lon, ax, xdist)
ax.set_title("Alarms general template")

# MAKE THE INSET
ax_inset = fig.add_axes([0.75, 0.75, 0.2, 0.2])
ax_inset = make_map(
    volc_lat,
    volc_lon,
    x_dist=500,
    y_dist=300,
    ax=ax_inset,
    basemap="land",
    projection="orthographic",
)

# INSET BOUNDING BOX
# bounding box delta degrees
d_deg_lat, d_deg_lon = create_bounding_box(
    lat=df.loc[volcano, "Latitude"],
    lon=df.loc[volcano, "Longitude"],
    ydist=ydist,
    xdist=xdist,
)
# get bounding box lat and lon bounds
latitude_min, latitude_max = volc_lat - d_deg_lat, volc_lat + d_deg_lat
longitude_min, longitude_max = volc_lon - d_deg_lon, volc_lon + d_deg_lon

# bounding box extent in cartopy argument format
extent = sgeom.box(longitude_min, latitude_min, longitude_max, latitude_max)
ax_inset.add_geometries(
    [extent],
    ccrs.PlateCarree(),
    facecolor="none",
    edgecolor="red",
    linewidth=0.35,
)
# rivers for reference in case it's just a gray blob
ax_inset.add_feature(cfeature.RIVERS, linewidth=0.5, linestyle=":")

print("saving template example")
plt.savefig(output_folder / "avo-alarms_map-general_example.png")
end = time.time()
print(f"DONE in {end - start:.2f} seconds")
