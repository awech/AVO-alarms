"""
Figure generation for the Magnitude alarm.

Builds the earthquake summary figure: a column of station waveform traces with
P/S phase markers and peak-amplitude labels, alongside a location map (with a
station layout, the epicenter, and an orthographic inset) titled with the
event time, magnitude, distance, and depth.
"""

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volc_alarms.utils import downloading, plotting, processing
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def get_xticks(st, fmt="15s"):
    """Compute relative-time x-ticks and clock-time labels for a trace.

    Builds tick positions (in seconds relative to the trace start) on a 15 s
    grid and formats each as an ``HH:MM:SS`` label, dropping a trailing tick
    that would fall past the end of the data.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose first trace defines the time span.
    fmt : str, optional
        Rounding frequency for the tick labels, by default ``"15s"``.

    Returns
    -------
    x_ticks : list of float
        Tick positions in seconds relative to the trace start.
    x_tick_labels : list of str
        ``HH:MM:SS`` labels for each tick.
    """
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
    """Build the mosaic layout and height ratios for the figure.

    Produces a single-column mosaic specification with a ``"map"`` panel on
    top, a spacer, then one panel per station, along with matching height
    ratios for :func:`matplotlib.pyplot.subplot_mosaic`.

    Parameters
    ----------
    st : obspy.Stream
        Stream whose traces determine the per-station panels.

    Returns
    -------
    axes_list : numpy.ndarray
        Column vector of mosaic panel labels.
    h_ratios : numpy.ndarray
        Height ratios aligned with ``axes_list``.
    """
    axes_list = np.array([tr.stats.station for tr in st])
    h_ratios = np.full(axes_list.shape, 1 / len(axes_list))
    axes_list = np.insert(axes_list, 0, ".")
    axes_list = np.insert(axes_list, 0, "map")
    h_ratios = np.insert(h_ratios, 0, 0)
    h_ratios = np.insert(h_ratios, 0, h_ratios.sum() * 0.5)
    axes_list = axes_list.reshape(axes_list.shape[0], 1)
    return axes_list, h_ratios


def plot_station_traces(ax, st, plot_chans):
    """Plot waveform traces with phase markers and amplitude labels.

    Removes instrument response (falling back to raw counts if that fails),
    trims and detrends, then draws each station's trace into its mosaic panel
    with P (red) and S (blue) phase markers and a rotated peak-amplitude label
    scaled to nm/s, um/s, or mm/s.

    Parameters
    ----------
    ax : dict
        Mapping of mosaic panel label to Axes (from ``subplot_mosaic``).
    st : obspy.Stream
        Station traces to plot (modified in place by response removal/trim).
    plot_chans : pandas.DataFrame
        Per-station channel info carrying ``P`` and ``S`` pick times.

    Returns
    -------
    None
    """
    try:
        client = downloading.Earthscope_client()
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
                tmp_str = f"{peak_num*1e6:.1f}\n$\\mu m/s$"
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


def plot_event(eq, volcs, config, n_stations=8, test=False):
    """Build the full earthquake summary figure.

    Downloads waveforms for the nearest ``n_stations`` picked channels, plots
    their traces, and renders a location map with the station layout, the
    epicenter, a scale bar, and an orthographic inset, titled with the event
    time, magnitude, distance to the nearest volcano, and depth.

    Parameters
    ----------
    eq : obspy.core.event.Event
        The earthquake event to plot.
    volcs : pandas.DataFrame
        Volcano list annotated with a ``distance`` column.
    config : object
        Magnitude alarm configuration (map distances, volcano overlay, output).
    n_stations : int, optional
        Maximum number of station traces to plot, by default 8.
    test : bool, optional
        Save with the test watermark/path when True, by default False.

    Returns
    -------
    pathlib.Path
        Path to the saved figure.
    """
    ################### Download data ###################
    channels = processing.eq_picks_to_dataframe(eq)
    plot_chans = channels[:n_stations]
    origin = eq.preferred_origin()
    st = downloading.download_waveforms(
        list(plot_chans.NSLC.values), origin.time - 20, origin.time + 50
    )
    st.merge()
    
    logger.info("Plotting traces...")
    axes_list, h_ratios = get_axes_and_ratios(st)
    fig, ax = plt.subplot_mosaic(
        axes_list,
        figsize=(4, 9),
        height_ratios=h_ratios,
    )

    plot_station_traces(ax, st, plot_chans)

    vlat = volcs.iloc[0]["Latitude"]
    vlon = volcs.iloc[0]["Longitude"]
    ax["map"], extent = plotting.make_map(
        ax["map"],
        vlat,
        vlon,
        basemap="hillshade",
        xdist=getattr(config, "map_distance", 50),
        ydist=getattr(config, "map_distance", 50)
    )

    plotting.map_ticks(ax["map"], extent, grid_kwargs="default", y_rotate=90)
    ax["map"].tick_params(length=0)

    plotting.add_volcanoes_to_map(ax["map"], extent, config)
    ax["map"].plot(channels.Longitude, channels.Latitude, 's', c='orange', ms=4, mec='k', mew=0.4, transform=ccrs.PlateCarree())
    ax["map"].plot(origin.longitude, origin.latitude, 'o', c='firebrick', ms=6, mec='k', mew=0.7, transform=ccrs.PlateCarree())
    for i, row in channels.iterrows():
        t = ax["map"].annotate(row.NS.split('.')[-1], (row.Longitude, row.Latitude), xytext=(10,10), textcoords="offset pixels", fontsize=6, transform=ccrs.Geodetic())
        t.clipbox = ax["map"].bbox

    plotting.add_scale_bar(ax["map"], 10, txt_yoffset=0.01, extent=extent)

    eq_t = origin.time.strftime("%Y-%m-%d %H:%M:%S")
    eq_mag = eq.preferred_magnitude().mag
    nearest = volcs.loc[volcs["distance"].idxmin()]
    eq_dist = nearest.distance
    volc = nearest.Name
    eq_depth = origin.depth / 1000
    title_str = (
        f"{eq_t}\n"
        f"M{eq_mag:.1f}, {eq_dist:.1f} km from {volc}\n"
        f"Depth: {eq_depth:.1f} km"
        )
    ax["map"].set_title(title_str, fontsize=8)

    ax_inset = fig.add_axes([0.66, 0.80, 0.12, 0.12])
    ax_inset, _ = plotting.make_map(
        ax_inset,
        vlat,
        vlon,
        xdist=getattr(config, "inset_map_distance", 150),
        ydist=getattr(config, "inset_map_distance", 150),
        basemap="land",
        projection="orthographic",
        water_color="white"
    )

    plotting.add_inset_polygon(ax_inset, extent)

    logger.info('Saving figure...')
    jpg_file = plotting.save_file(fig, config, test=test)

    return jpg_file
