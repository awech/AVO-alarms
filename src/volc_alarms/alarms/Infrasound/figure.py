import time

import matplotlib.pyplot as plt
from obspy import Stream

from volc_alarms.utils import downloading, plotting
from volc_alarms.utils.setup_utils import get_logger
from .detection import xcorr_align_stream

logger = get_logger(__name__)


def make_figure(st, target, T0, config, mx_pressure, test=False):

    start = time.time()

    ##### get seismic data #####
    t_seis_win = config.seismic_plot_duration if hasattr(config, "seismic_plot_duration") else 3600
    seis = downloading.download_waveforms(target["seismic_nslc"], T0 - t_seis_win, T0, fill_value="interpolate")
    ##### get infrasound data #####
    infra_nslc = [tr.id for tr in st]
    t_infra_win = config.infrasound_plot_duration if hasattr(config, "infrasound_plot_duration") else 600
    infra = downloading.download_waveforms(infra_nslc, T0 - t_infra_win, T0, fill_value="interpolate")

    logger.info(f"{time.time() - start:.2f} seconds to grab figure data.")

    #### preprocess data ####
    infra.detrend("demean")
    infra.taper(max_percentage=None, max_length=config.taper_val)
    infra.filter("bandpass", freqmin=config.f1, freqmax=config.f2)
    [tr.decimate(2, no_filter=True) for tr in infra if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in infra if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in infra if tr.stats.sampling_rate != 25]

    seis.detrend("demean")
    [tr.decimate(2, no_filter=True) for tr in seis if tr.stats.sampling_rate == 100]
    [tr.decimate(2, no_filter=True) for tr in seis if tr.stats.sampling_rate == 50]
    [tr.resample(25) for tr in seis if tr.stats.sampling_rate != 25]

    ##### stack infrasound data #####
    logger.info("stacking infrasound data")
    stack = xcorr_align_stream(infra, config)

    ##### set up figure #####
    seis_list = [[f"{tr.stats.station}.{tr.stats.channel}"] for tr in seis]
    axes_list = [["stack_spec"], ["stack_trace"], ["blank"]] + seis_list
    fig, ax = plt.subplot_mosaic(axes_list, figsize=(4.5, 4.5))
    ax["blank"].axis("off")

    ################# plot infrasound #################

    ##### plot stack spectrogram #####
    plotting.plot_spectrogram(ax["stack_spec"], stack)
    ax["stack_spec"].set_title(config.alarm_name + " Alarm: " + target["name"] + " detection!")
    ax["stack_spec"].set_xticks([])

    ##### plot stack trace #####
    ax["stack_trace"].plot(stack.times(), stack.data, color="k", linewidth=0.2)
    ax["stack_trace"].set_yticks([])
    ax["stack_trace"].set_xlim(stack.times()[0], stack.times()[-1])
    stack_st = Stream(stack)
    plotting.format_spec_xaxis(ax["stack_trace"], stack, stack_st, len(stack_st), config, duration=t_infra_win)
    for ax_lab in ["stack_trace", "stack_spec"]:
        ax[ax_lab].set_ylabel(
            stack.stats.station + "\nstack",
            fontsize=5,
            rotation="horizontal",
            multialignment="center",
            horizontalalignment="right",
            verticalalignment="center",
            color="red",
        )

    min_stamp = round(t_infra_win / 60)
    t_stamp = infra[0].stats.starttime.strftime("%Y-%b-%d")
    ax["stack_trace"].set_xlabel(
        f"{min_stamp:.0f} Minute Infrasound Stack\n{t_stamp} UTC,   Peak Pressure: {mx_pressure:.1f} Pa",
        fontsize=6,
    )
    ###################################################

    ################## plot seismic ###################
    for i, tr in enumerate(seis):
        name = f"{tr.stats.station}.{tr.stats.channel}"
        plotting.plot_spectrogram(ax[name], tr)
        plotting.format_spec_xaxis(ax[name], tr, seis, i, config)
        ax[name].set_title("")

    min_stamp = round(t_seis_win / 60)
    ax[name].set_xlabel(
        f"{min_stamp:.0f} Minute Seismic Local Seismic Data",
        fontsize=6,
    )
    ###################################################

    plt.subplots_adjust(left=0.08, right=0.94, top=0.92, bottom=0.1, hspace=0.1)

    jpg_file = plotting.save_file(fig, config, test=test, dpi=250)

    return jpg_file
