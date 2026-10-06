"""Smoke tests for ``volc_alarms.alarms.Infrasound.figure.make_figure``.

Intent: catch a plain bug (a rename, bad index, broken f-string, a feature
addition that raises) that would make figure generation blow up. In production
``make_figure`` runs inside a try/except so a failure never blocks an alert, but
we still want to know if an edit broke it. This is a *smoke* test -- it asserts
the builder runs end to end and returns a path, NOT that the figure looks right.

To keep it fast and deterministic, the two genuinely expensive/external things
are faked: ``download_waveforms`` (serves synthetic array + local traces) and
``do_LTS`` (returns a canned results frame instead of running the LTS solver).
``save_file`` is mocked to a sentinel so nothing is written to disk. The real
mosaic layout, azimuth-unwrapping, velocity-limit, tick-sync, spectrogram, and
divider code all run.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from matplotlib import dates
from obspy import Stream, Trace, UTCDateTime

from volc_alarms.alarms.Infrasound import figure as infra_figure

pytestmark = pytest.mark.unit

T0 = UTCDateTime("2026-05-14T22:56:00")
SENTINEL_JPG = "/tmp/__sentinel_infrasound_figure__.jpg"

# KENI array channels (present in the test station XML, so add_metadata /
# remove_gain resolve coordinates + response for them).
ARRAY_NSLC = [f"AV.KENI.0{i}.HDF" for i in range(1, 7)]


def _trace(nslc, t1, t2, sr, amp=1.0, freq=2.0):
    net, sta, loc, chan = nslc.split(".")
    npts = int(round((t2 - t1) * sr)) + 1
    t = np.arange(npts) / sr
    tr = Trace(data=(amp * np.sin(2 * np.pi * freq * t)).astype("float64"))
    tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel = net, sta, loc, chan
    tr.stats.sampling_rate = sr
    tr.stats.starttime = t1
    return tr


@pytest.fixture
def wired(monkeypatch):
    """Fake download_waveforms (synthetic streams), do_LTS (canned df), save_file."""

    def _download(nslc_list, t1, t2):
        st = Stream()
        for nslc in nslc_list:
            chan = nslc.split(".")[3]
            # Infrasound (HDF) at 100 Hz; local seismic (BHZ etc.) at 100 Hz too.
            st += _trace(nslc, t1, t2, sr=100.0, amp=1.0 if chan.endswith("DF") else 5.0)
        return st

    def _do_lts(st, config, skip_chans=None):
        # Canned LTS results spanning [T0-90, T0]; columns match what make_figure
        # reads. Azimuths near the KENI arrival, a few windows.
        n = 8
        times = [dates.date2num((T0 - 90).datetime) + i * (90 / n) / 86400.0 for i in range(n)]
        df = pd.DataFrame(
            {
                "Time": times,
                "Azimuth": np.linspace(210.0, 225.0, n),
                "Velocity": np.full(n, 340.0),  # m/s
                "MCCM": np.linspace(0.6, 0.95, n),
                "Pressure": np.linspace(0.5, 0.8, n),
                "Sigma_tau": np.full(n, 0.01),
                "Vel_err": np.full(n, 5.0),
                "Baz_err": np.full(n, 2.0),
            }
        )
        return df, {}

    monkeypatch.setattr(infra_figure.downloading, "download_waveforms", _download)
    monkeypatch.setattr(infra_figure.detection, "do_LTS", _do_lts)
    monkeypatch.setattr(infra_figure.plotting, "save_file", lambda *a, **k: SENTINEL_JPG)


def _config(targets):
    """Minimal Infrasound config sufficient for make_figure (array + processing).

    ``targets`` is included because make_figure calls get_target_backazimuth,
    which iterates config.targets; each target here already carries a
    back_azimuth, so that helper leaves them unchanged.
    """
    return SimpleNamespace(
        alarm_name="KENI Infrasound",
        nslc=list(ARRAY_NSLC),
        targets=targets,
        f1=0.5,
        f2=8.0,
        taper=5.0,
        duration=90,
        min_chan=3,
        min_channels=3,
        max_gap_fraction=0.5,
        lts_window_length=30,
        lts_overlap=15,
        lts_alpha=0.5,
        lts_n_samples=100,
    )


def _target(name, back_azimuth, with_local):
    t = {
        "name": name,
        "az_tolerance": 5,
        "min_pa": 0.5,
        "vmin": 0.28,
        "vmax": 0.4,
        "back_azimuth": back_azimuth,
        "plot_duration": 600,
    }
    if with_local:
        t["local_nslc"] = ["AV.Q19K..BHZ", "AV.KARR..BHZ"]
    return t


def test_make_figure_runs_with_local_spectrograms(wired):
    """make_figure completes and returns a path for a target with local_nslc.

    Exercises the spectrogram branch (the local seismic rows) end to end.
    """
    target = _target("Fourpeaked", back_azimuth=216.2, with_local=True)
    result = infra_figure.make_figure(
        target, T0, _config([target]), mx_pressure=0.8, test=False
    )
    assert result == SENTINEL_JPG


def test_make_figure_runs_without_local_channels(wired):
    """make_figure completes for an infrasound-only target (no local_nslc)."""
    target = _target("Katmai", back_azimuth=221.6, with_local=False)
    result = infra_figure.make_figure(
        target, T0, _config([target]), mx_pressure=0.6, test=False
    )
    assert result == SENTINEL_JPG


def test_make_figure_handles_backazimuth_wraparound(wired):
    """make_figure runs when the target back-azimuth forces 0/360 unwrapping.

    A near-North target with a wide tolerance makes the azimuth plot window
    straddle the 0/360 boundary, exercising the unwrap/fold branch.
    """
    target = _target("NearNorth", back_azimuth=5.0, with_local=False)
    result = infra_figure.make_figure(
        target, T0, _config([target]), mx_pressure=0.7, test=False
    )
    assert result == SENTINEL_JPG
