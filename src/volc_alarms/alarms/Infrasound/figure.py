import time

import matplotlib.pyplot as plt
from matplotlib import dates
from matplotlib import ticker
from matplotlib.dates import DateFormatter
import numpy as np

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
    infra = processing.add_metadata(infra)

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
    for tr in infra:
        tr.remove_sensitivity(tr.inventory)

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
    ax["infra_trace"].set_title(config.alarm_name + " Alarm: " + target["name"] + " detection!", fontsize=8)
    ax["infra_trace"].set_ylabel("Pressure\n[Pa]", fontsize=5)
    # Compact y-ticks: few ticks + scientific offset for small/noise values
    ax["infra_trace"].yaxis.set_major_locator(ticker.MaxNLocator(3))
    _pa_fmt = ticker.ScalarFormatter(useMathText=True)
    _pa_fmt.set_powerlimits((-1, 2))
    ax["infra_trace"].yaxis.set_major_formatter(_pa_fmt)
    ax["infra_trace"].yaxis.get_offset_text().set_fontsize(5)

    ##### plot infrasound backazimuth #####
    sc = ax["azimuth"].scatter(
        lts_df["Time"],
        lts_df["Azimuth"],
        c=lts_df["MCCM"],
        s=scatter_size,
        edgecolors="k",
        lw=scatter_lw,
        cmap=mycolormap,
    )
    sc.set_clim([0.2, 1.0])
    ax["azimuth"].axhline(target["back_azimuth"], ls='--', lw=1, color='gray', zorder=-1)
    ax["azimuth"].text(lts_df["Time"][1], target["back_azimuth"], target["name"], bbox=box_style, fontsize=6, va='center', style='italic', zorder=10)
    daz_factor = 5
    ax["azimuth"].set_ylim([target["back_azimuth"] - daz_factor*target["az_tolerance"], target["back_azimuth"] + daz_factor*target["az_tolerance"]])
    ax["azimuth"].set_ylabel("Backazimuth", fontsize=5)

    ##### plot infrasound velocity #####
    ax["velocity"].axhspan(
        target["vmin"],
        target["vmax"],
        facecolor="gray",
        alpha=0.25,
        edgecolor=None,
        )
    ax["velocity"].scatter(
        lts_df["Time"],
        lts_df["Velocity"]/1000,
        c=lts_df["MCCM"],
        s=scatter_size,
        edgecolors="k",
        lw=scatter_lw,
        cmap=mycolormap,
    )
    if hasattr(target, "array_label") and target["array_label"] == "Hydroacoustic":
        ax["velocity"].set_ylim(1.2, 1.8)  # Typical range for hydroacoustic arrays
    else:
        ax["velocity"].set_ylim(0.15, 0.6)  # Typical range for other arrays
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

    # Apply shared locator/formatter and xlim to every subplot
    for key in all_ax_keys:
        ax[key].set_xlim(xlim_left, xlim_right)
        ax[key].xaxis.set_major_locator(dates.AutoDateLocator(minticks=5, maxticks=8))
        ax[key].xaxis.set_major_formatter(DateFormatter("%H:%M"))
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
        ax["divider"].text(
            0.5, 0.7, "\u2191   Infrasound Array Results   \u2191",
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
