import os
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# from matplotlib_scalebar.scalebar import ScaleBar
from cartopy.io.img_tiles import GoogleTiles
from matplotlib.dates import date2num, num2date
from matplotlib.path import Path as mpath
from obspy import UTCDateTime as utc
from PIL import Image


class ShadedReliefESRI(GoogleTiles):
    """
    create a hillshade from esri

    Example:
    ```python
    fig,ax = plt.subplots(subplot_kw={'projection': ccrs.PlateCarree()})

    ax.add_image(ShadedReliefEsri(), zoom_level, alpha)
    ax.set_extent(extent)
    ```
    """

    def _image_url(self, tile):
        x, y, z = tile
        url = (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}.jpg"
        ).format(z=z, y=y, x=x)
        return url


def get_extent(lat0, lon0, dist=20):

    dlat = 1 * (dist / 111.1)
    dlon = dlat / np.cos(lat0 * np.pi / 180)

    latmin = lat0 - dlat
    latmax = lat0 + dlat
    lonmin = lon0 - dlon
    lonmax = lon0 + dlon

    return [lonmin, lonmax, latmin, latmax]


def make_path(extent):
    """
    make a matplotlib Path based on a list formatted for
    a matplotlib geoAxes.set_extent(). Useful for clipping axes to
    lat, lon boundaries when they are not rectangular in 2D space.
    DOES NOT WORK WITH MERCATOR PROJECTION - use with projections that make non
    rectangular lat,lon boxes in 2D space e.g., Orthographic, AlbersEqualArea

    Example:
    ```python
    fig,ax = plt.subplots(subplot_kw = {'projection': ccrs.Orthographic})
    extent = [longitude_min, longitude_max, latitude_min, latitude_max]
    ax.set_boundary(make_path(extent), transform=ccrs.Geodetic())

    Parameters
    ----------
    extent : list
        list of lat lon values formatted for matplotlib.geoAxes.set_extent() -
        [longitude_min, longitude_max, latitude_min, latitude_max]

    Return
    matplotlib Path object representing the desired extent
    ```
    """
    n = 20
    aoi = mpath.Path(
        list(zip(np.linspace(extent[0], extent[1], n), np.full(n, extent[3])))
        + list(zip(np.full(n, extent[1]), np.linspace(extent[3], extent[2], n)))
        + list(zip(np.linspace(extent[1], extent[0], n), np.full(n, extent[2])))
        + list(zip(np.full(n, extent[0]), np.linspace(extent[2], extent[3], n)))
    )

    return aoi


def great_circle_distance(origin, destination):
    """_summary_

    Parameters
    ----------
    origin : _type_
        _description_
    destination : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """
    lat1, lon1 = origin
    lat2, lon2 = destination
    radius = 6371  # km

    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) * np.sin(dlat / 2) + np.cos(np.radians(lat1)) * np.cos(
        np.radians(lat2)
    ) * np.sin(dlon / 2) * np.sin(dlon / 2)
    c = 2 * np.atan2(np.sqrt(a), np.sqrt(1 - a))
    d = radius * c

    return d


def get_bounding_box_limits(lat, lon, ydist, xdist):
    """
    get the lat and lon limits a user specified distance from a central point.
    Effectively converts distance from a central point to degrees.

    For more maths:
    longitude - https://en.wikipedia.org/wiki/Longitude#Length_of_a_degree_of_longitude
    latitude - https://en.wikipedia.org/wiki/Latitude#Length_of_a_degree_of_latitude

    Used for when you want to effectively create bounding boxes around a central point

    Example:
    ```python
    # for creating cartopy extents

    d_deg_lat, d_deg_lon = get_bounding_box_limits(
        lat=volc_lat, lon=volc_lon, xdist=x_dist, ydist=y_dist
    )
    # get bounding box lat and lon bounds
    latitude_min, latitude_max = volc_lat - d_deg_lat, volc_lat + d_deg_lat
    longitude_min, longitude_max = volc_lon - d_deg_lon, volc_lon + d_deg_lon

    # bounding box extent in cartopy argument format
    extent = [longitude_min, longitude_max, latitude_min, latitude_max]
    ```

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


def make_map(
    volc_lat,
    volc_lon,
    ax,
    x_dist=25.0,
    y_dist=None,
    basemap="hillshade",
    projection="mercator",
    land_color="#80808050",
):
    """
    make the basemap for all AVO alarms that require maps.
    This function is incredibly flexible to allow for use in both main
    and inset maps.

    Example:
    ```python
    # A basic alarms template with a main map and inset axis:
    fig, ax = plt.subplots(figsize=(6, 6))


    # NORMAL MAP uses the default x_dist of 25
    ax = make_map(
        volc_lat,
        volc_lon,
        ax=ax,
        basemap="hillshade",
    )
    ax.set_title("Alarms general template")
    # INSET MAP
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
    ```

    Parameters
    ----------
    volc_lat : float
        volcano or central point latitude
    volc_lon : float
        volcano or central point longitude
    ax : matplotlib.Axes
        the matplotlib axis to create the map on
    x_dist : float, optional
        E-W distance from the central point in km, by default 25.
    y_dist : float, optional
        N-S distance from the central point in km, by default None.
        If None, then y_dist = x_dist / 1.5. This creates relatively
        square plots at AK latitudes
    basemap : str, optional
        what type of basemap to use. Options are:
        'hillshade' - uses ShadedReliefEsri()
        'land' - uses cartopy.cfeature.LAND
        'boring' - uses cartopy.cfeature.STATES
        by default 'hillshade'
    projection : str, optional
        which map projection to use. Options are:
        'mercator' - uses ccrs.Mercator(central_longitude=volc_lon)
        'orthographic' - uses ccrs.Orthographic(central_longitude=volc_lon,central_latitude=volc_lat)
        'albers' - uses ccrs.AlbersEqualArea(central_longitude=volc_lon,central_latitude=volc_lat)
        'nearside' - uses ccrs.NearsidePerspective(central_longitude=volc_lon,central_latitude=volc_lat)
        by default "mercator". Note if basemap = 'hillshade', projection is forced to "mercator"
        as this is the projection for the ShadedReliefEsri() image
    land_color : str, optional
        what color land you want? by default "#80808050"

    Returns
    -------
    ax
        matplotlib.geoAxes
    """

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
    d_deg_lat, d_deg_lon = get_bounding_box_limits(
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
    """
    Add gridlines the way jubb and awech like them on their maps.

    Example:
    ```python
    # A basic alarms template main map with gridlines
    fig, ax = plt.subplots(figsize=(6, 6))


    # NORMAL MAP uses the default x_dist of 25
    ax = make_map(
        volc_lat,
        volc_lon,
        ax=ax,
        basemap="hillshade",
    )
    gl = add_map_grid(volc_lat, volc_lon, ax)
    ax.set_title("Alarms general template")
    ```

    Parameters
    ----------
    volc_lat : float
        volcano or central point latitude
    volc_lon : float
        volcano or central point longitude
    ax : ax : matplotlib.Axes
        the matplotlib axis to create the map on
    x_dist : float, optional
        E-W distance from the central point in km, by default 25.
    y_dist : float, optional
        N-S distance from the central point in km, by default None.
        If None, then y_dist = x_dist / 1.5. This creates relatively
        square plots at AK latitudes
    fontsize : int, optional
       fontsize for the lat-lon labels, by default 6

    Returns
    -------
    cartopy.mpl.gridliner.Gridliner
        yer gridlines object. Can be further customized outside this
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
    # so the axis is relatvely square at AK lats
    if y_dist is None:
        y_dist = x_dist / 1.5

    d_lat, d_lon = get_bounding_box_limits(
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


def add_watermark(text, ax=None):
    """Add a watermark to a figure

    Args:
        text (str): the text to add as a watermark
        ax (matplotlib Axes object, optional): the matplotlib axis to add the watermark to.
        Defaults to None. if `None` then `plt.gca` is used.
    """
    if ax is None:
        ax = plt.gca()

    ax.text(
        0.5,
        0.5,
        text,
        transform=ax.transAxes,
        fontsize=50,
        color="gray",
        alpha=0.5,
        va="center",
        ha="center",
    )


def save_file(plt, config, dpi=250):
    """_summary_

    Parameters
    ----------
    plt : _type_
        _description_
    config : _type_
        _description_
    dpi : int, optional
        _description_, by default 250

    Returns
    -------
    _type_
        _description_
    """
    home_dir = Path(os.environ["HOME_DIR"])

    png_file = (
        home_dir
        / f"{config.alarm_name.replace(' ','_')}_{utc.utcnow().strftime('%Y%m%d_%H%M%S')}.png"
    )
    jpg_file = (
        home_dir
        / f"{config.alarm_name.replace(' ','_')}_{utc.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
    )

    plt.savefig(png_file, dpi=dpi, format="png")
    im = Image.open(png_file)
    im.convert("RGB").save(jpg_file, "JPEG")
    os.remove(png_file)

    return jpg_file


def time_ticks(
    axes,
    starttime,
    endtime,
    dt_freq,
    fmt="%Y-%m-%d",
    relative=False,
    axis="x",
    rotation=45,
    ha="right",
    **kwargs,
):
    """Set the xlims and xticks with a specific start and end dates.
    To be called after finished all plotting so the axes and ticks aren't subsequently modified.

    Parameters
    ----------
    axes : _matplotlib axis object_
        the axes object you wanna make more better
    starttime : str | pandas timestamp
        start time for tick generation and left x-axis limit. Can be string or pandas timestamp object
    endtime : str | pandas timestamp
        end time for tick generation and right x-axis limit. Can be string or pandas timestamp object
    dt_freq : str
        pandas frequency alias, typically a number and string combo, e.g.: 5 days = "5D"
        can also be negative, so values will start from the endtime, e.g.: "-5D"
        for string alias info, see:
        https://pandas.pydata.org/docs/user_guide/timeseries.html#timeseries-offset-aliases
    fmt : str, optional
        datestr format, by default "%Y-%m-%d"
    relative : bool, optional
        set to True if x-axis is in seconds instead of datetime (e.g., spectrogram), by default False
    axis : str, optional
        Which axis you want to pin: "x", "y", by default "x"
    rotation : float, optional
        tick label rotation, by default 45
    ha : str, optional
        tick label horizontal alignment, by default "right"
    **kwargs :
        other customizations passed on to set_xticklabels()
    """

    if isinstance(starttime, str):
        starttime = pd.to_datetime(starttime)
    if isinstance(endtime, str):
        endtime = pd.to_datetime(endtime)
    if dt_freq[0] == "-":
        ticks = pd.date_range(endtime, starttime, freq=dt_freq)
    else:
        ticks = pd.date_range(starttime, endtime, freq=dt_freq)

    tick_labels = [ti.strftime(fmt) for ti in ticks]

    T0 = date2num(starttime)
    T1 = date2num(endtime)

    if relative:
        ticks = 86400 * (date2num(ticks) - T0)

    if axis == "x":
        if relative:
            axes.set_xlim(0, 86400 * (T1 - T0))
        else:
            axes.set_xlim(num2date(T0), num2date(T1))
        axes.set_xticks(ticks)
        axes.set_xticklabels(tick_labels, rotation=rotation, ha=ha, **kwargs)
    elif axis == "y":
        if relative:
            axes.set_ylim(0, 86400 * (T1 - T0))
        else:
            axes.set_ylim(num2date(T0), num2date(T1))
        axes.set_yticks(ticks)
        axes.set_yticklabels(tick_labels, rotation=rotation, ha=ha, **kwargs)
        axes.set_yticks(ticks)
        axes.set_yticklabels(tick_labels, rotation=rotation, ha=ha, **kwargs)
