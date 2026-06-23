import os
import time
import importlib
from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import shapely.geometry as sgeom
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from cartopy.io.img_tiles import GoogleTiles
from cartopy.mpl.gridliner import LongitudeFormatter, LatitudeFormatter
import matplotlib as m
from matplotlib.dates import date2num, num2date
from matplotlib.path import Path as mpath
from matplotlib.colors import LinearSegmentedColormap
from obspy import UTCDateTime as utc
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list
from volc_alarms.utils import downloading, processing

logger = get_logger(__name__)
m.use("Agg")

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
            f"World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}.jpg"
        )
        return url


def get_extent(lat0, lon0, xdist=25, ydist=25):
    """Get a cartopy extent using x & y distance from a lat,lon point

    Parameters
    ----------
    lat0 : float
        center point latitude
    lon0 : float
        center point longitude
    xdist : float, optional
        longitude width (in km) of desired resulting map bounds, by default 25
    ydist : float, optional
        latitude width (in km) of desired resulting map bounds, by default 25

    Returns
    -------
    list
        [lonmin, lonmax, latmin, latmax] list of bounds for cartopy map
    """
    
    dx = xdist / 2
    dy = ydist / 2
    
    dlat = dy / 111.1
    dlon = (dx / 111.1) / np.cos(lat0 * np.pi / 180)

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
    ax,
    volc_lat,
    volc_lon,
    xdist=25.0,
    ydist=25.0,
    basemap="hillshade",
    projection="mercator",
    land_color="#CBCBCBFF",
    water_color="#B8F1FF",
    extent=None
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

    possible_basemaps = ["BORING", "HILLSHADE", "LAND", "HIGHRES"]
    assert (
        basemap in possible_basemaps
    ), f"{basemap} not in possible basemaps. please choose boring or hillshade"

    if not extent:
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
    ax.set_extent(extent, crs=ccrs.Geodetic())  # defaults to geodetic version of crs

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
        ax.patch.set_facecolor(water_color)

    elif basemap == "HIGHRES":
        coast = cfeature.GSHHSFeature(scale="full")
        ax.add_feature(coast, facecolor=land_color, linewidth=0.2, alpha=1)
        ax.patch.set_facecolor(water_color)

    # cant use set_boundary on mercator for some reason.
    if projection != "MERCATOR":
        ax.set_boundary(make_path(extent), transform=ccrs.Geodetic())

    return ax, extent


def add_volcanoes_to_map(ax, extent, config, c1="forestgreen", c2="darkseagreen", s1=25, s2=20, ec1="k", ec2="k", **kwargs):

    volcs = load_volcano_list()
    volcs = volcs[
        (volcs.Latitude >= extent[2]) & (volcs.Latitude <= extent[3]) & (volcs.Longitude >= extent[0]) & (volcs.Longitude <= extent[1])
    ]
    volcs["distance"] = np.sqrt(
        (volcs.Latitude - (extent[2] + extent[3]) / 2) ** 2
        + (volcs.Longitude - (extent[0] + extent[1]) / 2) ** 2
    )
    volcs = volcs.sort_values("distance")
    N = len(volcs)
    ax.scatter(volcs.Longitude.values, volcs.Latitude.values,
            c=[c1] + [c2]*(N-1),
            s=np.array([s1] + [s2]*(N-1)),
            marker="^",
            edgecolors=[ec1] + [ec2]*(N-1),
            transform=ccrs.Geodetic(),
            zorder=1e2,
            linewidths=kwargs.pop("linewidths", 0.5),
            **kwargs)


def add_scale_bar(ax, length_km, location=(0.1, 0.05), txt_yoffset=0.02, extent=None):

    # 1. Get current map extent to find positioning
    # TODO fix bug when lon0=-180, lon1=180 when spanning dateline
    # added `extent` argument as quick bandaid, but should be implemented wholesale
    if not extent:
        lon0, lon1, lat0, lat1 = ax.get_extent(ccrs.PlateCarree())
    else:
        lon0, lon1, lat0, lat1 = extent

    sb_lon = lon0 + (lon1 - lon0) * location[0]
    sb_lat = lat0 + (lat1 - lat0) * location[1]

    # 2. Calculate degrees of longitude for exactly 'length_km'
    # 111.32 km is approx 1 degree at the equator
    delta_lon = length_km / (111.32 * np.cos(np.radians(sb_lat)))

    # 3. Plot the bar using PlateCarree transform (lat/lon)
    ax.plot([sb_lon, sb_lon + delta_lon], [sb_lat, sb_lat], 
            transform=ccrs.PlateCarree(), color='black', linewidth=1, zorder=5)
    
    # 4. Add the label
    ax.text(sb_lon + (delta_lon/2), sb_lat + txt_yoffset, f'{length_km} km', 
            transform=ccrs.PlateCarree(), ha='center', va='bottom', fontsize=5)


def add_inset_polygon(ax, extent, fc="none", ec="red", lw=0.35, **kwargs):
    extent_new = [sgeom.box(extent[0], extent[2], extent[1], extent[3])]
    ax.add_geometries(
        extent_new,
        ccrs.PlateCarree(),
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        **kwargs,
    )


def get_xticks(st, fmt="15s"):
    trace_t1 = pd.to_datetime(st[0].stats.starttime.datetime)
    trace_t2 = pd.to_datetime(st[0].stats.endtime.datetime)
    tick_df = pd.DataFrame({"datetime": pd.date_range(trace_t1, trace_t2, freq="15s")})
    x_tick_labels = tick_df["datetime"].dt.ceil(fmt)
    x_ticks = [(xt - trace_t1).total_seconds() for xt in x_tick_labels]
    x_tick_labels = [xt.strftime("%H:%M:%S") for xt in x_tick_labels]
    if x_ticks[-1] > st[0].times()[-1]:
        x_ticks = x_ticks[:-1]
        x_tick_labels = x_tick_labels[:-1]
    return x_ticks, x_tick_labels


def get_axes_and_ratios(st):
    axes_list = np.array([tr.stats.station for tr in st])
    h_ratios = np.full(axes_list.shape, 1 / len(axes_list))
    axes_list = np.insert(axes_list, 0, ".")
    axes_list = np.insert(axes_list, 0, "map")
    h_ratios = np.insert(h_ratios, 0, 0)
    h_ratios = np.insert(h_ratios, 0, h_ratios.sum() * 0.5)
    axes_list = axes_list.reshape(axes_list.shape[0], 1)

    return axes_list, h_ratios


def plot_station_traces(ax, st, plot_chans):

    try:
        client = processing.IRIS_client()
        client._attach_responses(st)
        st.remove_response()
        velocity = True
    except Exception as e:
        logger.warning(f"Problem occurred while removing response: {e}")
        velocity = False

    st.trim(st[0].stats.starttime + 5, st[0].stats.endtime - 5)
    st.detrend()

    x_ticks, x_tick_labels = get_xticks(st)
    
    for i, tr in enumerate(st):
        sta = tr.stats.station
        ax[sta].plot(tr.times("relative"), tr.data, lw=0.5, c="0.2")
        ax[sta].text(
            0.01,
            0.7,
            tr.id,
            fontsize=6,
            transform=ax[sta].transAxes,
            bbox=dict(boxstyle="round", fc="w", ec="w", alpha=0.8, linewidth=0),
        )
        trace_t1 = tr.stats.starttime.datetime
        try:
            p_time = (plot_chans.iloc[i].P.datetime - trace_t1).total_seconds()
            ax[sta].axvline(p_time, ymin=0.25, ymax=0.75, color="r", linewidth=1)
        except Exception as e:
            logger.warning(f"Problem plotting P phase arrivals for station {sta}")
            logger.warning(e)
            pass
        try:
            s_time = (plot_chans.iloc[i].S.datetime - trace_t1).total_seconds()
            ax[sta].axvline(s_time, ymin=0.25, ymax=0.75, color="dodgerblue", linewidth=1)
        except Exception as e:
            logger.warning(f"Problem plotting S phase arrivals for station {sta}")
            logger.warning(e)
            pass
        if i == 4:
            tr.data = tr.data * 1e3
        if velocity:
            label_color = "black"
            fw = "normal"
            peak_num = np.abs(tr.data).max()
            if np.log10(peak_num) < -6:
                tmp_str = f"{peak_num*1e9:.1f}\n$nm/s$"
            elif np.log10(peak_num) < -3:
                tmp_str = f"{peak_num*1e6:.1f}\n$\mu$$m/s$"
            elif np.log10(peak_num) < 0:
                tmp_str = f"{peak_num*1e3:.2f}\n$mm/s$"
                label_color = "firebrick"
                fw = "bold"
            ax[sta].text(
                ax[sta].get_xlim()[0] - 1 / 86400,
                tr.data[0],
                tmp_str,
                fontsize=6,
                horizontalalignment="center",
                verticalalignment="bottom",
                rotation_mode="anchor",
                rotation=90,
                color=label_color,
                fontweight=fw,
            )
        ax[sta].set_yticks([])
        ax[sta].set_xticks(x_ticks)
        ax[sta].set_xticklabels([])
        ax[sta].grid(axis="x", linewidth=0.2, linestyle="--")
        ax[sta].tick_params("x", length=0)
        for spine in ["top", "bottom", "left", "right"]:
            ax[sta].spines[spine].set_visible(False)
    ax[sta].set_xticklabels(x_tick_labels, fontsize=6)

    return


def default_grid_params(**kwargs):
    grid_kwargs = {
        "ls": "--",
        "color": "gray",
        "alpha": 0.5,
        "linewidth": 0.25,
        "draw_labels": {"top": False, "bottom": True, "left": False, "right": True},
        "xlabel_style": {"size": 6},
        "ylabel_style": {"size": 6},
    }
    grid_kwargs.update(kwargs)
    return grid_kwargs


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

    for i, xloc in enumerate(xlocs):
        if xloc < -180:
            xlocs[i] = xloc + 360

    if grid_kwargs == "default":
        grid_kwargs = default_grid_params()

    if grid_kwargs is not None:
        grid_kwargs["xformatter"] = lon_formatter
        grid_kwargs["yformatter"] = lat_formatter
        gl = ax.gridlines(xlocs=xlocs, ylocs=ylocs, **grid_kwargs)
        if "xlabel_style" in grid_kwargs:
            gl.xlabel_style = grid_kwargs["xlabel_style"]
        if "ylabel_style" in grid_kwargs:
            gl.ylabel_style = grid_kwargs["ylabel_style"]
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


def add_watermark(fig, text):
    """Add a watermark to a figure

    Args:
        fig (matplotlib Figure object): the matplotlib figure to add the watermark to.
        text (str): the text to add as a watermark
    """
    
    fig_width_pts = fig.get_figwidth() * fig.dpi
    fontsize = fig_width_pts * 0.1 
    logger.info(f"Adding watermark with fontsize {fontsize}")

    fig.text(
        0.5,
        0.5,
        text,
        transform=fig.transFigure,
        fontsize=fontsize,
        color="red",
        alpha=0.5,
        va="center",
        ha="center",
        rotation=30
    )


def save_file(fig, config, test=False, dpi=250):
    """_summary_

    Parameters
    ----------
    fig : _type_
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
    home_dir = Path(os.environ["TMP_FIGURE_DIR"])

    jpg_file = (
        home_dir
        / f"{config.alarm_name.replace(' ','_')}_{utc.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
    )

    if test:
        add_watermark(fig, "TEST ALARM")

    fig.savefig(jpg_file, dpi=dpi, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)

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


def default_colormap(infrasound=False):
    if importlib.util.find_spec("cmcrameri") is not None:
        from cmcrameri import cm
        colors = cm.roma_r(np.linspace(-1, 1.2, 256))
    else:
        import matplotlib.cm as cm
        colors = cm.jet(np.linspace(-1, 1.2, 256))
    if infrasound:
        import matplotlib.cm as cm_infra
        colors = cm_infra.viridis(np.linspace(-1,1.2,256))
        
    color_map = LinearSegmentedColormap.from_list("Upper Half", colors)
    return color_map


def plot_spectrogram(ax, tr, colormap=default_colormap()):

    label_color = "black"
    if tr.stats.channel in ["BDF", "HDF", "EDH"]:
        colormap = default_colormap(infrasound=True)
        label_color = "red"

    tr.spectrogram(
        title="",
        log=False,
        samp_rate=tr.stats.sampling_rate,
        dbscale=True,
        per_lap=0.5,
        mult=25.0,
        wlen=6,
        cmap=colormap,
        axes=ax,
    )
    ax.set_yticks([3, 6, 9, 12])
    ax.set_ylabel(
        tr.stats.station + "\n" + tr.stats.channel,
        fontsize=5,
        rotation="horizontal",
        multialignment="center",
        horizontalalignment="right",
        verticalalignment="center",
        color=label_color,
    )
    ax.yaxis.set_ticks_position("right")
    ax.tick_params("y", labelsize=4)


def format_spec_xaxis(ax, tr, st, i, config, duration=None):

    if duration is None:
        duration = config.plot_duration if hasattr(config, "plot_duration") else 3600

    if i == 0:
        ax.set_title(config.alarm_name + " Alarm")
    if i < len(st) - 1:
        ax.set_xticks([])
    else:
        tick_fmt = "%H:%M"
        if duration in [1800, 3600, 5400, 7200]:
            n_ticks = 7
        elif duration in np.arange(300, 3600, 300):
            n_ticks = 6
        else:
            n_ticks = 6
            tick_fmt = "%H:%M:%S"
        d_sec = np.linspace(0, duration, n_ticks)
        ax.set_xticks(d_sec)
        T = [tr.stats.starttime + dt for dt in d_sec]
        ax.set_xticklabels([t.strftime(tick_fmt) for t in T])
        ax.tick_params("x", labelsize=5)
        ax.set_xlabel(tr.stats.starttime.strftime("%Y-%b-%d"))


def plot_spectrogram_figure(nslc, T0, config, test=False):
    """Shared spectrogram-mosaic figure builder.

    Originally RSAM.make_figure; extracted here so both RSAM and Tremor
    alarm modules can share the same plotting logic.

    Parameters
    ----------
    nslc : list
        List of NSLC strings to plot.
    T0 : obspy.UTCDateTime
        End time of the plot window.
    config : object
        Alarm configuration object (must have at least `alarm_name`;
        optionally `plot_duration`).
    test : bool, optional
        If True, stamp the figure with a TEST watermark, by default False.

    Returns
    -------
    pathlib.Path
        Path to the saved JPG figure file.
    """

    #### grab data ####
    start = time.time()
    t_win = getattr(config, "plot_duration", 3600)
    st = downloading.download_waveforms(
        nslc, T0 - t_win - config.taper, T0 + config.taper
    )
    logger.info(f"{time.time() - start:.2f} seconds to grab figure data.")

    #### preprocess data ####
    st.detrend("demean")
    [tr.decimate(2, no_filter=True) for tr in st if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in st if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in st if tr.stats.sampling_rate != 25]
    st.merge()
    st.trim(T0 - t_win, T0, pad=True)

    #### generate the figure ####
    axes_list = [[f"{i_nslc}"] for i_nslc in nslc]
    fig, ax = plt.subplot_mosaic(axes_list, figsize=(4.5, 4.5))

    for i, i_nslc in enumerate(nslc):
        tr = st.select(id=i_nslc)[0]
        plot_spectrogram(ax[tr.id], tr)
        format_spec_xaxis(ax[tr.id], tr, st, i, config)

    plt.subplots_adjust(left=0.08, right=0.94, top=0.92, bottom=0.1, hspace=0.1)

    jpg_file = save_file(fig, config, test=test, dpi=250)

    return jpg_file
