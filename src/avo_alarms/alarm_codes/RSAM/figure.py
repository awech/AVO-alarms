from avo_alarms.utils import plotting


def make_figure(nslc, T0, config, test=False):
    """Thin wrapper delegating to the shared spectrogram-figure builder."""
    return plotting.plot_spectrogram_figure(nslc, T0, config, test=test)
