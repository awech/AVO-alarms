import os
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import shapely.geometry as sgeom
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from cartopy.io.img_tiles import GoogleTiles
from cartopy.mpl.gridliner import LongitudeFormatter, LatitudeFormatter
from matplotlib.dates import date2num, num2date
from matplotlib.path import Path as mpath
from obspy import UTCDateTime as utc


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


def get_extent(lat0, lon0, xdist=25, ydist=25):

    dlat = ydist / 111.1
    dlon = (xdist / 111.1) / np.cos(lat0 * np.pi / 180)

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
    aoi = mpath(
        list(zip(np.linspace(extent[1], extent[0], n), np.full(n, extent[3])))
        + list(zip(np.full(n, extent[0]), np.linspace(extent[3], extent[2], n)))
        + list(zip(np.linspace(extent[0], extent[1], n), np.full(n, extent[2])))
        + list(zip(np.full(n, extent[1]), np.linspace(extent[2], extent[3], n)))
    )

    return aoi


def make_map(
    volc_lat,
    volc_lon,
    ax,
    xdist=25.0,
    ydist=25.0,
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


    # NORMAL MAP uses the default xdist of 25
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
        xdist=500,
        ydist=300,
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
    xdist : float, optional
        E-W distance from the central point in km, by default 25.
    ydist : float, optional
        N-S distance from the central point in km, by default None.
        If None, then ydist = xdist / 1.5. This creates relatively
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

    extent = get_extent(volc_lat, volc_lon, xdist=xdist, ydist=ydist)

    # how detailed to make the hillshade scales to how
    # big of an area to map

    if xdist <= 50:
        zoom_level = 13
    elif (xdist > 50) & (xdist <= 100):
        zoom_level = 11
    elif (xdist > 100) & (xdist < 500):
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

    # cant use set_boundary on mercator for some reason.
    if projection != "MERCATOR":
        ax.set_boundary(make_path(extent), transform=ccrs.Geodetic())

    ax.set_extent(extent, crs=ccrs.Geodetic())  # defaults to geodetic version of crs

    return ax


def add_inset_polygon(ax, extent, **kwargs):
    extent_new = [sgeom.box(extent[0], extent[2], extent[1], extent[3])]
    ax.add_geometries(
        extent_new,
        ccrs.PlateCarree(),
        **kwargs,
    )


def map_ticks(ax, extent, nticks_x=2, nticks_y=2, grid_kwargs=None, lon_fmt_kwargs=None, lat_fmt_kwargs=None, y_rotate=None, ticks_right=True):
    """Adds ticks and/or grid to a cartopy map axis at specified locations.

    Parameters
    ----------
    ax : cartopy axis
        
    xlocs : list or numpy array
        longitudes of grids and/or xticks
    ylocs : list or numpy array
        latitudes of grids and/or xticks
    grid_kwargs : dict, optional
        additional arguments for cartopy's ax.gridlines(), by default None
        https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.grid.html
    lon_fmt_kwargs : dict, optional
        arguments for cartopy's LongitudeFormatter(), by default None
        https://scitools.org.uk/cartopy/docs/v0.22/reference/generated/cartopy.mpl.ticker.LongitudeFormatter.html
    lat_fmt_kwargs : dict, optional
        arguments for cartopy's LatitudeFormatter(), by default None
        https://scitools.org.uk/cartopy/docs/v0.22/reference/generated/cartopy.mpl.ticker.LatitudeFormatter.html
    y_rotate : float, optional
        rotate y-ticklabels, by default None
    ticks_right : bool, optional
        move y-axis ticks to the right, by default True

    Returns
    -------
    None, or:
        Gridliner() instance if grid_kwargs are passed AND grid_kwargs["draw_labels"]=True
    """

    if lon_fmt_kwargs is None:
        lon_formatter = LongitudeFormatter(
            number_format=".2f", dateline_direction_label=True, direction_label=True,
        )
    else:
        lon_formatter = LongitudeFormatter(**lon_fmt_kwargs)
    if lat_fmt_kwargs is None:
        lat_formatter = LatitudeFormatter(number_format=".2f", direction_label=True)
    else:
        lat_formatter = LatitudeFormatter(**lat_fmt_kwargs)

    xlocs = np.linspace(extent[0], extent[1], nticks_x+2)[1:-1]
    ylocs = np.linspace(extent[2], extent[3], nticks_y+2)[1:-1]

    for i, l in enumerate(xlocs):
        if l < -180:
            xlocs[i] = l + 360 

    if grid_kwargs is not None:
        grid_kwargs["xformatter"] = lon_formatter
        grid_kwargs["yformatter"] = lat_formatter
        gl = ax.gridlines(xlocs=xlocs, ylocs=ylocs, **grid_kwargs)
        if "draw_labels" in grid_kwargs and grid_kwargs["draw_labels"]:
            return gl

    ax.set_xticks(xlocs, crs=ccrs.PlateCarree())
    ax.set_yticks(ylocs, crs=ccrs.PlateCarree())
    if y_rotate is not None:
        ax.set_yticklabels(
            ylocs,
            rotation=y_rotate,
            ha="center",
            rotation_mode="anchor",
        )
        ax.tick_params(axis="y", pad=7)

    ax.xaxis.set_major_formatter(lon_formatter)
    ax.yaxis.set_major_formatter(lat_formatter)
    if ticks_right:
        ax.yaxis.tick_right()


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


def save_file(fig, config, dpi=250):
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

    jpg_file = (
        home_dir
        / f"{config.alarm_name.replace(' ','_')}_{utc.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
    )

    fig.savefig(jpg_file, dpi=dpi)

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
