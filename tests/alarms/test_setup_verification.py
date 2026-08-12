"""Smoke tests for the test harness itself.

Verifies that the shared fixtures and doubles work correctly before relying
on them in the golden baseline tests:

* Real configs load from config/ directory
* Doubles replace external I/O and record calls in order
* The FROMCRON fixture toggles the environment variable
* Figure builders return placeholder paths

These tests do NOT capture golden baselines or test alarm detection logic.
"""

from __future__ import annotations

import os

from obspy import Stream, UTCDateTime

from volc_alarms.utils import alarming, downloading, messaging, plotting


def test_load_real_config_from_repo_config_dir(load_alarm_config):
    """A genuine config object loads from the in-repo config/ directory."""
    config = load_alarm_config("RSAM")
    assert config.alarm_type == "RSAM"
    assert config.alarm_name == "Semisopochnoi RSAM"
    # CONFIGS_DIR points at the repo's config/ directory.
    assert os.environ["CONFIGS_DIR"].endswith("/config")


def test_download_waveforms_double_returns_canned_stream(alarm_doubles):
    """download_waveforms is replaced and returns a canned, gap-free Stream."""
    nslc = ["AV.PS4A..BHZ", "AV.PVV..BHZ"]
    t1 = UTCDateTime("2024-01-01T00:00:00")
    t2 = t1 + 300
    st = downloading.download_waveforms(nslc, t1, t2)
    assert isinstance(st, Stream)
    assert len(st) == 2
    assert {tr.id for tr in st} == set(nslc)
    assert alarm_doubles.recorder.called("download_waveforms")


def test_messaging_doubles_record_without_io(alarm_doubles, load_alarm_config):
    """post_mattermost / send_alert / icinga record calls and perform no I/O."""
    config = load_alarm_config("RSAM")
    url = messaging.post_mattermost(config, "subj", "body", attachment=None, send=True)
    messaging.send_alert(config.alarm_name, "subj", "body")
    messaging.icinga(config, "OK", "all good", send=True)

    assert url == alarm_doubles.mm_url
    assert alarm_doubles.call_names() == ["post_mattermost", "send_alert", "icinga"]
    # args captured for later assertions
    assert alarm_doubles.recorder.first("post_mattermost").args[1] == "subj"


def test_alarming_doubles_use_in_memory_db(alarm_doubles, load_alarm_config):
    """can_send returns the configured result; record_send writes to memory."""
    config = load_alarm_config("RSAM")
    t0 = UTCDateTime("2024-01-01T00:00:00")

    alarm_doubles.can_send_result = True
    assert alarming.can_send(config, T0=t0) is True

    alarm_doubles.can_send_result = False
    assert alarming.can_send(config, T0=t0) is False

    alarming.record_send(config, t0, volcano="Semisopochnoi", event_id="evt-1")
    assert len(alarm_doubles.db.records) == 1
    rec = alarm_doubles.db.records[0]
    # VOLCANO_NAME on the config overrides the volcano arg, mirroring production.
    assert rec["alarm_id"] == "Semisopochnoi RSAM"
    assert rec["volcano"] == "Semisopochnoi"
    assert rec["event_id"] == "evt-1"


def test_save_file_and_os_remove_doubles(alarm_doubles, load_alarm_config):
    """plotting.save_file returns the placeholder path; os.remove is recorded."""
    config = load_alarm_config("RSAM")
    path = plotting.save_file(fig=None, config=config)
    assert path == alarm_doubles.placeholder_figure

    os.remove(path)
    assert alarm_doubles.recorder.called("os.remove")
    assert alarm_doubles.recorder.last("os.remove").args[0] == alarm_doubles.placeholder_figure


def test_relocated_download_doubles_return_canned_fixtures(alarm_doubles):
    """The per-alarm download/scrape helpers are replaced with canned returns.

    After task 10.1, these functions live in their owning alarm packages
    (not in utils/downloading), so we call them from their new homes.
    """
    from volc_alarms.alarms.Pilot_Report import detection as pirep_detection
    from volc_alarms.alarms.SO2 import detection as so2_detection
    from volc_alarms.alarms.Lightning import detection as lightning_detection

    assert pirep_detection.download_pilot_reports(None, None) == ("OK", None)
    assert so2_detection.download_SO2() == (None, None)
    assert lightning_detection.download_lightning() is None
    assert alarm_doubles.recorder.names() == [
        "download_pilot_reports",
        "download_SO2",
        "download_lightning",
    ]


def test_fromcron_helper_toggles_environment(fromcron):
    """The fromcron fixture sets and clears the FROMCRON env var."""
    fromcron("yep")
    assert os.environ["FROMCRON"] == "yep"
    fromcron(None)
    assert "FROMCRON" not in os.environ


def test_patch_figure_builder_returns_placeholder(alarm_doubles):
    """patch_figure_builder swaps an alarm's make_figure for a placeholder double."""
    from volc_alarms import RSAM

    alarm_doubles.patch_figure_builder(RSAM, "make_figure")
    result = RSAM.make_figure(["AV.PS4A..BHZ"], UTCDateTime("2024-01-01"), object())
    assert result == alarm_doubles.placeholder_figure
    assert alarm_doubles.recorder.called("make_figure")
