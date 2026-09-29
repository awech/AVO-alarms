"""Smoke test for ``volc_alarms.alarms.NOAA_CIMSS.figure.plot_fig``.

``plot_fig`` reads the two alert images that ``get_cimss_image`` downloaded to
``TMP_DIR`` (``noaa_out_1.png`` / ``noaa_out_2.png``), lays them above a cartopy
map centered on the alert's radiative center, saves the figure, and removes the
two temp images. This drives that render offline for a real recorded Spurr ash
alert using the two committed alert PNGs, staged into ``TMP_DIR`` first.

``save_file`` is mocked to a sentinel so no jpg is written; matplotlib runs
headless on Agg. Like the other figure tests this is a *smoke* test: it asserts
the render runs end to end, returns a path, and cleans up its temp images.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from volc_alarms.alarms.NOAA_CIMSS import figure as cimss_figure
from volc_alarms.utils.setup_utils import TMP_DIR

pytestmark = pytest.mark.unit

DATA = Path("tests/fixtures/data")
IMG1_FIXTURE = DATA / "noaa_cimss_alert_448880_img1.png"
IMG2_FIXTURE = DATA / "noaa_cimss_alert_448880_img2.png"

SENTINEL_JPG = "/tmp/__sentinel_noaa_cimss_figure__.jpg"


def _alert():
    """The recorded Spurr ash alert, as a Series (what run_alarm passes plot_fig)."""
    return pd.Series(
        {
            "object_date_time": "2026-09-29 14:30:38",
            "alert_header": "POSSIBLE VOLCANIC ASH CLOUD FOUND",
            "method": "Plume/Puff Extraction (SECO+)",
            "lat_rc": 61.30,
            "lon_rc": -152.25,
        }
    )


def _config():
    return SimpleNamespace(alarm_name="NOAA CIMSS")


@pytest.fixture
def staged_images(monkeypatch):
    """Stage the two recorded alert PNGs where plot_fig reads them; sentinel save."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp1 = TMP_DIR / "noaa_out_1.png"
    tmp2 = TMP_DIR / "noaa_out_2.png"
    shutil.copyfile(IMG1_FIXTURE, tmp1)
    shutil.copyfile(IMG2_FIXTURE, tmp2)

    monkeypatch.setattr(cimss_figure.plotting, "save_file", lambda *a, **k: SENTINEL_JPG)

    yield tmp1, tmp2

    # plot_fig removes these on success; clean up if a test failed before that.
    for f in (tmp1, tmp2):
        if f.exists():
            f.unlink()


def test_plot_fig_runs_and_returns_path(staged_images):
    """plot_fig renders the two images + map and returns the saved-figure path."""
    result = cimss_figure.plot_fig(_alert(), _config(), test=False)
    assert result == SENTINEL_JPG


def test_plot_fig_removes_temp_images(staged_images):
    """plot_fig deletes the two temp alert images after saving."""
    tmp1, tmp2 = staged_images
    cimss_figure.plot_fig(_alert(), _config(), test=False)
    assert not tmp1.exists()
    assert not tmp2.exists()
