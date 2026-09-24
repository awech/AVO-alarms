import time

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import dates, ticker
from matplotlib.dates import DateFormatter
from obspy import Stream

from volc_alarms.utils import downloading, plotting, processing
from volc_alarms.utils.setup_utils import get_logger

from . import detection

logger = get_logger(__name__)

mycolormap = "RdYlBu_r"
box_style = {'facecolor': 'white', 'edgecolor': 'white', 'pad': 0}
scatter_size = 8
scatter_lw = 0.1


def add_mccm_colorbar(ax1, ax2, fig, sc):
    """
    Add a colorbar for the MCCM (Multi-Channel Cross-Matching) results.

    Args:
        ax1 (matplotlib.axes.Axes): The axes for the first subplot.
        ax2 (matplotlib.axes.Axes): The axes for the second subplot.
        fig (matplotlib.figure.Figure): The figure containing the axes.
        sc (matplotlib.collections.PathCollection): The scatter plot object for MCCM results.
    """
    
    ctop = ax1.get_position().y1
    cbot = ax2.get_position().y0
    cbaxes_mccm = fig.add_axes([0.91, cbot, 0.02, ctop - cbot])
    hc = plt.colorbar(sc, cax=cbaxes_mccm, ticks=np.arange(0.2, 1.01, 0.2))
    hc.set_label(r'$M_{d}CCM$', fontsize=6)


def make_figure(target, T0, config, mx_pressure, test=False):

    start = time.time()
    t_win = target.get("plot_duration")
    logger.info(f"Making ({t_win/60:.0f} minutes) figure for target {target['name']}")
    t1 = T0 - t_win
    t2 = T0

    ##### determine whether local seismic data is configured #####
    if hasattr(target, "get"):
        local_nslc = target.get("local_nslc") or []
    else:
        local_nslc = getattr(target, "local_nslc", None) or []
    has_local = len(local_nslc) > 0

    ##### get local seismic data #####
    local_st = None
    if has_local:
        logger.info("Grabbing local data...")
        local_st = downloading.download_waveforms(local_nslc, t1 - config.taper, t2 + config.taper)
    else:
        logger.info("No local_nslc configured for target; rendering infrasound-only figure.")

    ##### get infrasound data #####
    infra_nslc = config.nslc
    logger.info("Grabbing infrasound array data...")
    infra = downloading.download_waveforms(infra_nslc, t1 - config.taper, t2 + config.taper)
    logger.info(f"{time.time() - start:.2f} seconds to grab figure data.")

    #### preprocess local seismic data ####
    if has_local:
        local_st.detrend("demean")
        [tr.decimate(2, no_filter=True) for tr in local_st if tr.stats.sampling_rate == 100]
        [tr.decimate(2, no_filter=True) for tr in local_st if tr.stats.sampling_rate == 50]
        [tr.resample(25) for tr in local_st if tr.stats.sampling_rate != 25]
        local_st.merge()
        local_st.trim(t1, t2, pad=True)

    #### preprocess infrasound data ####
    infra = processing.preprocess_stream(infra, t1, t2, config)
    good_data, skip_chans = detection.QC_data(infra, config)
    # Add coordinates/inventory metadata, then remove gain
    infra = Stream([tr for tr in infra if tr.id not in skip_chans])
    if isinstance(config.nslc, dict):
        # Manual metadata from config: attach coordinates and divide by gain
        for tr in infra:
            params = config.nslc[tr.id]
            tr.stats.coordinates = {"latitude": params["lat"], "longitude": params["lon"], "elevation": 0.0}
            tr.data = tr.data / params["gain"]
    else:
        # Lookup from station XML
        infra = processing.add_metadata(infra)
        infra = processing.remove_gain(infra)

    #### run LTS ####
    config = detection.get_target_backazimuth(infra, config)
    lts_df, lts_dict = detection.do_LTS(infra, config)

    ################## Start Figure Making ##################
    #########################################################

    ##### set up figure #####
    if has_local:
        local_list = [[f"{i_nslc}"] for i_nslc in local_nslc]
        axes_list = [["infra_trace"], ["azimuth"], ["velocity"], ["divider"]] + local_list
        # Full-height rows for data, short row for the section divider
        n_spec = len(local_list)
        height_ratios = [1, 1, 1, 0.35] + [1] * n_spec
        figsize = (4.5, 6.5)
    else:
        axes_list = [["infra_trace"], ["azimuth"], ["velocity"]]
        height_ratios = [1, 1, 1]
        figsize = (4.5, 3.5)
    fig, ax = plt.subplot_mosaic(
        axes_list, figsize=figsize, height_ratios=height_ratios
    )

    ##### common x-axis limits in datenum space #####
    xlim_left = dates.date2num(t1.datetime)
    xlim_right = dates.date2num(t2.datetime)

    ################# plot infrasound #################

    ##### plot infrasound trace #####
    plot_trace_id = getattr(config, "plotchan", infra[0].id)
    tr = infra.select(id=plot_trace_id)[0]
    tvec = np.linspace(
        dates.date2num(tr.stats.starttime.datetime),
        dates.date2num(tr.stats.endtime.datetime),
        len(tr.data),
    )
    ax["infra_trace"].plot(tvec, tr.data, lw=0.2, c="k")
    bound = np.max(np.abs(ax["infra_trace"].get_ylim()))
    ax["infra_trace"].set_ylim(-bound, bound)
    ax["infra_trace"].set_title(config.alarm_name + " Alarm: " + target["name"] + " detection!", fontsize=8)
    ax["infra_trace"].set_ylabel("Pressure\n[Pa]", fontsize=5)
    # Compact y-ticks: few ticks + scientific offset for small/noise values
    ax["infra_trace"].yaxis.set_major_locator(ticker.MaxNLocator(3))
    _pa_fmt = ticker.ScalarFormatter(useMathText=True)
    _pa_fmt.set_powerlimits((-1, 2))
    ax["infra_trace"].yaxis.set_major_formatter(_pa_fmt)
    ax["infra_trace"].yaxis.get_offset_text().set_fontsize(5)
    # Note the channel and frequency on the right side
    ax2 = ax["infra_trace"].twinx()
    ax2.set_yticks([])
    ax2.set_ylabel(
        f"{tr.id}\n"
        "--------------------\n"
        f"{config.f1:.1f} - {config.f2:.1f} Hz",
        labelpad=4,
        fontsize=5,
    )

    ##### plot infrasound backazimuth #####
    baz_target = target["back_azimuth"]
    daz_factor = 5
    # Nominal plot window centered on the target. Cap the half-window at 180
    # deg so the axis never spans more than a full 360 deg circle (e.g. when
    # az_tolerance is large).
    half_window = min(daz_factor * target["az_tolerance"], 180)
    ymin = baz_target - half_window
    ymax = baz_target + half_window

    # If the window runs above 360, slide it (and the target line) down by
    # 360 so plotted values stay <= 360. Negative values are acceptable.
    if ymax > 360:
        ymin -= 360
        ymax -= 360
        baz_target -= 360

    # Only unwrap the azimuths if the plot window straddles the 0/360
    # boundary; otherwise leave the raw 0-360 values untouched. Unwrapping
    # shifts each measurement to the copy nearest the window center, keeping
    # near-boundary points (and their error bars) clustered. Use >=/<= so a
    # window edge landing exactly on 0 or 360 still folds points inward.
    if ymin <= 0 or ymax >= 360:
        center = (ymin + ymax) / 2
        az_plot = center + (((lts_df["Azimuth"] - center) + 180) % 360 - 180)
        # Fold any points that landed above the window top down by 360 so
        # plotted values never exceed 360 (negatives are acceptable).
        az_plot = az_plot.where(az_plot <= ymax, az_plot - 360)
    else:
        az_plot = lts_df["Azimuth"]

    ax["azimuth"].errorbar(
        lts_df["Time"],
        az_plot,
        yerr=lts_df["Baz_err"],
        fmt="none",
        ecolor="gray",
        elinewidth=0.2,
        zorder=-1,
    )
    sc = ax["azimuth"].scatter(
        lts_df["Time"],
        az_plot,
        c=lts_df["MCCM"],
        s=scatter_size,
        edgecolors="k",
        lw=scatter_lw,
        cmap=mycolormap,
    )
    sc.set_clim([0.2, 1.0])
    ax["azimuth"].axhline(baz_target, ls='--', lw=1, color='gray', zorder=-1)
    ax["azimuth"].text(lts_df["Time"][1], baz_target, target["name"], bbox=box_style, fontsize=6, va='center', style='italic', zorder=10)
    # Use the nominal +/- daz_factor*az_tolerance window as-is (no expansion
    # to chase points/error bars, which could be far-field LTS outliers).
    # Keep the <=360 guard on the top edge.
    ymax = min(ymax, 360)
    ax["azimuth"].set_ylim([ymin, ymax])
    ax["azimuth"].set_ylabel("Backazimuth", fontsize=5)

    ##### plot infrasound velocity #####
    ax["velocity"].axhspan(
        target["vmin"],
        target["vmax"],
        facecolor="gray",
        alpha=0.25,
        edgecolor=None,
        )
    ax["velocity"].errorbar(
        lts_df["Time"],
        lts_df["Velocity"] / 1000,
        yerr=lts_df["Vel_err"] / 1000,
        fmt="none",
        ecolor="gray",
        elinewidth=0.2,
        zorder=-1,
    )
    sc2 = ax["velocity"].scatter(
        lts_df["Time"],
        lts_df["Velocity"] / 1000,
        c=lts_df["MCCM"],
        s=scatter_size,
        edgecolors="k",
        lw=scatter_lw,
        cmap=mycolormap,
    )
    sc2.set_clim([0.2, 1.0])

    if hasattr(target, "array_label") and target["array_label"] == "Hydroacoustic":
        vmin_plot = target["vmin"] - 0.1 if target["vmin"] <= 1.2 else 1.2
        vmax_plot = target["vmax"] + 1.8 if target["vmax"] >= 1.8 else 1.8
    else:
        vmin_plot = target["vmin"] - 0.1 if target["vmin"] <= 0.15 else 0.15
        vmax_plot = target["vmax"] + 0.1 if target["vmax"] >= 0.6 else 0.6

    ax["velocity"].set_ylim(vmin_plot, vmax_plot)  # Typical range for other arrays
    ax["velocity"].set_ylabel("Velocity\n[km/s]", fontsize=5)

    add_mccm_colorbar(ax["azimuth"], ax["velocity"], fig, sc)

    ##### plot local spectrograms #####
    if has_local:
        for i, i_nslc in enumerate(local_nslc):
            tr = local_st.select(id=i_nslc)[0]
            plotting.plot_spectrogram(ax[tr.id], tr)
            # Rescale spectrogram x-axis from seconds to datenums
            spec_t_start = dates.date2num(tr.stats.starttime.datetime)
            spec_t_end = dates.date2num(tr.stats.endtime.datetime)
            ax[tr.id].set_xlim(spec_t_start, spec_t_end)
            # The spectrogram was plotted in seconds; remap the x-axis via image extent
            for img in ax[tr.id].images:
                sec_extent = img.get_extent()
                img.set_extent([spec_t_start, spec_t_end, sec_extent[2], sec_extent[3]])

    ##### synchronize all x-axes #####
    all_ax_keys = ["infra_trace", "azimuth", "velocity"]
    if has_local:
        all_ax_keys += [nslc for nslc in local_nslc]

    # Determine tick format and count based on window duration
    tick_fmt = plotting.set_time_ticks(ax[all_ax_keys[0]], xlim_left, xlim_right, t_win)

    # Apply shared locator/formatter and xlim to every subplot
    tick_locations = ax[all_ax_keys[0]].get_xticks()
    for key in all_ax_keys:
        ax[key].set_xlim(xlim_left, xlim_right)
        ax[key].xaxis.set_major_locator(ticker.FixedLocator(tick_locations))
        ax[key].xaxis.set_major_formatter(DateFormatter(tick_fmt))
        ax[key].tick_params("x", labelbottom=False, length=2)

    # The mplstyle enables ytick.right; disable it on the non-spectrogram
    # (top 3) subplots so they only show y-ticks on the left
    for key in ["infra_trace", "azimuth", "velocity"]:
        ax[key].tick_params("y", right=False)

    # Only the bottom subplot shows tick labels + date as xlabel
    bottom_key = all_ax_keys[-1]
    ax[bottom_key].tick_params("x", labelbottom=True, labelsize=6)
    ax[bottom_key].set_xlabel(t1.strftime("%Y-%b-%d"), fontsize=8)

    ##### dashed divider + section labels between infrasound and spectrograms #####
    if has_local:
        ax["divider"].axis("off")
        # dashed horizontal line across most of the divider axis
        ax["divider"].axhline(0.5, xmin=0.0, xmax=1.0, color="gray", ls="--", lw=0.75)
        # labels above and below the line
        if hasattr(target, "array_label"):
            divider_text = f"{target['array_label']} Array Results"
        else:
            divider_text = "Infrasound Array Results"
        ax["divider"].text(
            0.5, 0.7, f"\u2191   {divider_text}   \u2191",
            transform=ax["divider"].transAxes,
            ha="center", va="bottom", fontsize=6,
        )
        ax["divider"].text(
            0.5, 0.3, "\u2193   Local Data   \u2193",
            transform=ax["divider"].transAxes,
            ha="center", va="top", fontsize=6,
        )

    ###################################################

    jpg_file = plotting.save_file(fig, config, test=test, dpi=250)

    return jpg_file
