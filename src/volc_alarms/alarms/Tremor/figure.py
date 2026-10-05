"""
Figure generation for the Tremor alarm.

Thin wrapper around the shared spectrogram-figure builder used by the Tremor
alarm's send sequence.
"""

from volc_alarms.utils import plotting


def make_figure(nslc, T0, config, test=False):
    """Build the Tremor spectrogram figure.

    Delegates to the shared spectrogram-figure builder.

    Parameters
    ----------
    nslc : list
        Network.station.location.channel ids to plot.
    T0 : obspy.UTCDateTime
        End time of the plotted window.
    config : object
        Alarm configuration, passed through to the figure builder.
    test : bool, optional
        Save with the test watermark/path when True, by default False.

    Returns
    -------
    pathlib.Path
        Path to the saved spectrogram figure.
    """
    return plotting.plot_spectrogram_figure(nslc, T0, config, test=test)
