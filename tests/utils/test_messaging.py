"""Unit tests for ``volc_alarms.utils.messaging``.

Focus on the pure formatting/helper logic. The network-bound senders
(``send_alert``/``post_mattermost``/``connect_mattermost``/``upload_mm_attachments``)
are exercised end to end by the integration harness; here we only unit-test the
parts that transform text/data and the ``send=False`` short-circuits.

The network-bound senders are unit-tested here with local fakes for the HTTP
(``requests``), SMTP (``smtplib``), and Mattermost (``mattermostdriver.Driver``)
boundaries — no sockets are opened. The integration harness still exercises the
same senders end to end against a frozen baseline.

Covered:
* attachments_tolist    — None/str/list normalization
* format_timestring     — UTC + local formatting, minute vs second precision, ranges
* format_nearest_volcanoes — "Name (dist km)" join, underscore->space, n cap
* format_mm_message     — markdown checkboxes + PIREP heading rules (incl. URGENT)
* icinga                — send=False no-op, success/non-200/exception send paths
* get_recipients_list   — named/All-Alarms/Test/Error groups, missing-phonebook skip
* send_alert            — SSL + STARTTLS, test-mode subject, attachments
* connect_mattermost    — Driver options from env + login()
* upload_mm_attachments — file-id collection, empty passthrough
* post_mattermost       — default/config/test channel, retry, volcano + channel fan-out
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from obspy import UTCDateTime
from pandas import DataFrame

from volc_alarms.utils import messaging

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# attachments_tolist
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, expected",
    [
        (None, []),
        ("", []),
        ("a.jpg", ["a.jpg"]),
        (["a.jpg", "b.jpg"], ["a.jpg", "b.jpg"]),
    ],
)
def test_attachments_tolist_normalizes_to_list(value, expected):
    """attachments_tolist wraps a scalar, passes a list, and maps falsy to []."""
    assert messaging.attachments_tolist(value) == expected


# ---------------------------------------------------------------------------
# format_timestring
# ---------------------------------------------------------------------------
def test_format_timestring_uses_minute_precision_on_round_times():
    """format_timestring uses %H:%M when the single time has zero seconds."""
    t1 = UTCDateTime("2025-01-01T00:30:00")
    out = messaging.format_timestring(t1)
    assert "2025-01-01 00:30 UTC" in out
    # No seconds field on a round minute.
    assert "00:30:00" not in out


def test_format_timestring_uses_second_precision_when_seconds_present():
    """format_timestring falls back to %H:%M:%S when seconds are non-zero."""
    t1 = UTCDateTime("2025-01-01T00:30:15")
    out = messaging.format_timestring(t1)
    assert "00:30:15" in out


def test_format_timestring_range_labels_start_and_end():
    """format_timestring with two times labels both Start and End in UTC."""
    t1 = UTCDateTime("2025-01-01T00:00:00")
    t2 = UTCDateTime("2025-01-01T01:00:00")
    out = messaging.format_timestring(t1, t2)
    assert "Start: 2025-01-01 00:00 (UTC)" in out
    assert "End: 2025-01-01 01:00 (UTC)" in out


# ---------------------------------------------------------------------------
# format_nearest_volcanoes
# ---------------------------------------------------------------------------
def test_format_nearest_volcanoes_joins_name_and_distance():
    """format_nearest_volcanoes renders 'Name (dist km)' sorted, underscores spaced."""
    volcs = DataFrame(
        {
            "Name": ["Mount_Spurr", "Redoubt", "Iliamna"],
            "distance": [12.3, 48.6, 70.1],
        }
    )
    out = messaging.format_nearest_volcanoes(volcs, n=2)
    assert out == "Mount Spurr (12 km), Redoubt (49 km)"


def test_format_nearest_volcanoes_empty_table_returns_empty_string():
    """format_nearest_volcanoes returns '' for an empty volcano table."""
    volcs = DataFrame({"Name": [], "distance": []})
    assert messaging.format_nearest_volcanoes(volcs) == ""


# ---------------------------------------------------------------------------
# format_mm_message
# ---------------------------------------------------------------------------
def test_format_mm_message_wraps_non_pirep_subject_as_h3():
    """format_mm_message renders a non-PIREP subject as a bold H3 heading."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    message = messaging.format_mm_message("--- RSAM detection ---", "body text", config)
    # The '---' framing is stripped and the subject becomes an H3.
    assert message.startswith("### **RSAM detection**")
    assert "body text" in message


def test_format_mm_message_pirep_non_urgent_uses_h4():
    """format_mm_message uses an H4 heading for a non-urgent PIREP subject."""
    config = SimpleNamespace(alarm_name="PIREP")
    message = messaging.format_mm_message("Pilot report", "body", config)
    assert message.startswith("#### **Pilot report**")


# ---------------------------------------------------------------------------
# send=False short-circuits (no network)
# ---------------------------------------------------------------------------
def test_icinga_send_false_is_a_noop():
    """icinga(send=False) returns without attempting any HTTP request."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    # Should not raise even though no ICINGA_* env vars are configured.
    assert messaging.icinga(config, "OK", "all good", send=False) is None


def test_post_mattermost_send_false_returns_empty_string():
    """post_mattermost(send=False) returns '' without connecting to a server."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    assert messaging.post_mattermost(config, "subj", "body", send=False) == ""


# ---------------------------------------------------------------------------
# format_timestring — local timezone + range precision branches
# ---------------------------------------------------------------------------
def test_format_timestring_single_includes_local_timezone_line(monkeypatch):
    """format_timestring renders a second UTC->local line using TIMEZONE."""
    monkeypatch.setenv("TIMEZONE", "US/Alaska")
    t1 = UTCDateTime("2025-01-01T00:30:00")
    out = messaging.format_timestring(t1)
    # UTC line plus a local-time line (Alaska is UTC-9 in Jan).
    assert "2025-01-01 00:30 UTC" in out
    assert "2024-12-31 15:30" in out  # local conversion


def test_format_timestring_range_second_precision_when_duration_not_whole_minute(monkeypatch):
    """format_timestring uses %H:%M:%S for a range whose span isn't a whole minute."""
    monkeypatch.setenv("TIMEZONE", "US/Alaska")
    t1 = UTCDateTime("2025-01-01T00:00:00")
    t2 = UTCDateTime("2025-01-01T00:00:30")  # 30s span -> seconds shown
    out = messaging.format_timestring(t1, t2)
    assert "Start: 2025-01-01 00:00:00 (UTC)" in out
    assert "End: 2025-01-01 00:00:30 (UTC)" in out


def test_format_timestring_range_includes_local_start_and_end(monkeypatch):
    """format_timestring with two whole-minute times adds local Start/End lines."""
    monkeypatch.setenv("TIMEZONE", "US/Alaska")
    t1 = UTCDateTime("2025-01-01T00:00:00")
    t2 = UTCDateTime("2025-01-01T01:00:00")
    out = messaging.format_timestring(t1, t2)
    # Local Alaska lines (UTC-9) for both ends.
    assert "Start: 2024-12-31 15:00" in out
    assert "End: 2024-12-31 16:00" in out


# ---------------------------------------------------------------------------
# format_mm_message — checkbox substitution + PIREP URGENT
# ---------------------------------------------------------------------------
def test_format_mm_message_checks_stations_that_exceeded_threshold():
    """format_mm_message renders '*'-flagged stations (value exceeded threshold) as checked boxes.

    RSAM/message.py appends '*' to a station's name when ``rsam > level`` (see
    ``create_message``), e.g. ``"SSLW*: 452/300"``. Those become checked boxes.
    """
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    body = "\nSSLW*: 452/300"
    message = messaging.format_mm_message("subj", body, config)
    assert "- [x] **SSLW**: 452/300" in message


def test_format_mm_message_leaves_sub_threshold_stations_unchecked():
    """format_mm_message renders unflagged station lines (below threshold) as unchecked boxes."""
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    # No '*' -> value did not exceed threshold -> unchecked box.
    body = "\nSSLS: 120/300"
    message = messaging.format_mm_message("subj", body, config)
    assert "- [ ] SSLS: 120/300" in message


def test_format_mm_message_pirep_urgent_uses_h3():
    """format_mm_message renders an URGENT PIREP subject as an H3 heading."""
    config = SimpleNamespace(alarm_name="PIREP")
    message = messaging.format_mm_message("URGENT pilot report", "body", config)
    assert message.startswith("### **URGENT pilot report**")


# ---------------------------------------------------------------------------
# icinga — send=True paths (requests mocked)
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"results": [{"status": "ok-status"}]}

    def json(self):
        return self._payload


@pytest.fixture
def icinga_env(monkeypatch):
    """Populate the ICINGA_* env vars icinga() reads."""
    monkeypatch.setenv("ICINGA_HOST_NAME", "host.example")
    monkeypatch.setenv("ICINGA_URL", "https://icinga.example/v1/actions")
    monkeypatch.setenv("ICINGA_USERNAME", "user")
    monkeypatch.setenv("ICINGA_PASSWORD", "pass")


def test_icinga_success_sends_request_with_expected_payload(monkeypatch, icinga_env):
    """icinga posts a Service check with the mapped exit status and message."""
    captured = {}

    def fake_get(url, headers=None, auth=None, data=None, verify=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["verify"] = verify
        return _FakeResponse(status_code=200)

    monkeypatch.setattr(messaging.requests, "get", fake_get)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    messaging.icinga(config, "CRITICAL", "boom")

    import json as _json

    payload = _json.loads(captured["data"])
    assert payload["exit_status"] == 2  # CRITICAL -> 2
    assert payload["plugin_output"] == "boom"
    assert 'service.name=="Pavlof RSAM"' in payload["filter"]
    assert captured["verify"] is False


def test_icinga_uses_explicit_service_name_when_configured(monkeypatch, icinga_env):
    """icinga prefers config.icinga_service_name over alarm_name for the service filter."""
    captured = {}

    def fake_get(url, headers=None, auth=None, data=None, verify=None, timeout=None):
        captured["data"] = data
        return _FakeResponse(status_code=200)

    monkeypatch.setattr(messaging.requests, "get", fake_get)

    config = SimpleNamespace(
        alarm_name="Pavlof RSAM", icinga_service_name="Custom Service"
    )
    messaging.icinga(config, "OK", "fine")

    import json as _json

    payload = _json.loads(captured["data"])
    assert 'service.name=="Custom Service"' in payload["filter"]
    assert payload["exit_status"] == 0


def test_icinga_non_200_logs_error_without_raising(monkeypatch, icinga_env):
    """icinga handles a non-200 response gracefully (no exception)."""
    monkeypatch.setattr(
        messaging.requests, "get", lambda *a, **k: _FakeResponse(status_code=500)
    )
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    assert messaging.icinga(config, "WARNING", "warn") is None


def test_icinga_request_exception_is_swallowed(monkeypatch, icinga_env):
    """icinga catches request exceptions and returns None."""

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(messaging.requests, "get", boom)
    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    assert messaging.icinga(config, "UNKNOWN", "???") is None


# ---------------------------------------------------------------------------
# get_recipients_list
# ---------------------------------------------------------------------------
@pytest.fixture
def dist_phonebook(monkeypatch, tmp_path):
    """Write a distribution.yml + phonebook.yml and point env vars at them."""
    dist = tmp_path / "distribution.yml"
    dist.write_text(
        "All Alarms:\n  - alice\n"
        "Pavlof RSAM:\n  - alice\n  - bob\n"
        "Test:\n  - alice\n"
        "Error:\n  - bob\n"
    )
    phone = tmp_path / "phonebook.yml"
    phone.write_text("alice: alice@example.com\nbob: bob@example.com\n")
    monkeypatch.setenv("DISTRIBUTION_FILE", str(dist))
    monkeypatch.setenv("PHONEBOOK_FILE", str(phone))
    return dist, phone


def test_get_recipients_list_returns_named_group(dist_phonebook):
    """get_recipients_list returns the addresses for a matching alarm group."""
    recipients = messaging.get_recipients_list("Pavlof RSAM")
    assert recipients == ["alice@example.com", "bob@example.com"]


def test_get_recipients_list_defaults_to_all_alarms(dist_phonebook):
    """get_recipients_list falls back to 'All Alarms' for an unknown alarm name."""
    recipients = messaging.get_recipients_list("Unknown Alarm")
    assert recipients == ["alice@example.com"]


def test_get_recipients_list_test_mode_uses_test_group(dist_phonebook):
    """get_recipients_list uses the 'Test' group when test=True and it exists."""
    recipients = messaging.get_recipients_list("Pavlof RSAM", test=True)
    assert recipients == ["alice@example.com"]


def test_get_recipients_list_test_mode_falls_back_to_error_group(
    monkeypatch, tmp_path
):
    """get_recipients_list uses 'Error' when test=True and no 'Test' group exists."""
    dist = tmp_path / "distribution.yml"
    dist.write_text("All Alarms:\n  - alice\nError:\n  - bob\n")
    phone = tmp_path / "phonebook.yml"
    phone.write_text("alice: alice@example.com\nbob: bob@example.com\n")
    monkeypatch.setenv("DISTRIBUTION_FILE", str(dist))
    monkeypatch.setenv("PHONEBOOK_FILE", str(phone))

    recipients = messaging.get_recipients_list("Pavlof RSAM", test=True)
    assert recipients == ["bob@example.com"]


def test_get_recipients_list_skips_users_absent_from_phonebook(monkeypatch, tmp_path):
    """get_recipients_list skips a distribution user missing from the phonebook."""
    dist = tmp_path / "distribution.yml"
    dist.write_text("All Alarms:\n  - alice\n  - ghost\n")
    phone = tmp_path / "phonebook.yml"
    phone.write_text("alice: alice@example.com\n")
    monkeypatch.setenv("DISTRIBUTION_FILE", str(dist))
    monkeypatch.setenv("PHONEBOOK_FILE", str(phone))

    recipients = messaging.get_recipients_list("All Alarms")
    assert recipients == ["alice@example.com"]


# ---------------------------------------------------------------------------
# send_alert — SMTP mocked (SSL + STARTTLS), attachments
# ---------------------------------------------------------------------------
class _FakeSMTP:
    """Records SMTP interactions without opening a socket."""

    instances = []

    def __init__(self, host=None, port=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.sent = None
        self.quit_called = False
        _FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.started_tls = True

    def sendmail(self, fromaddr, recipients, text):
        self.sent = {"from": fromaddr, "to": recipients, "text": text}

    def quit(self):
        self.quit_called = True


@pytest.fixture
def smtp_env(monkeypatch, dist_phonebook):
    """SMTP env vars + a recipient list via dist_phonebook."""
    monkeypatch.setenv("SMTP_IP", "smtp.example")
    monkeypatch.setenv("SMTP_PORT", "465")
    _FakeSMTP.instances.clear()


def test_send_alert_uses_ssl_by_default(monkeypatch, smtp_env):
    """send_alert connects via SMTP_SSL when SMTP_SECURITY is unset/ssl."""
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setattr(messaging.smtplib, "SMTP_SSL", _FakeSMTP)

    messaging.send_alert("Pavlof RSAM", "subj", "body")

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls is False  # SSL path doesn't call starttls
    assert smtp.quit_called is True
    assert smtp.sent["from"] == "Pavlof_RSAM@usgs.gov"
    assert smtp.sent["to"] == ["alice@example.com", "bob@example.com"]


def test_send_alert_starttls_path(monkeypatch, smtp_env):
    """send_alert uses SMTP + STARTTLS when SMTP_SECURITY=starttls."""
    monkeypatch.setenv("SMTP_SECURITY", "starttls")
    monkeypatch.setattr(messaging.smtplib, "SMTP", _FakeSMTP)

    messaging.send_alert("Pavlof RSAM", "subj", "body")

    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls is True


def test_send_alert_test_mode_prefixes_subject(monkeypatch, smtp_env):
    """send_alert prefixes the subject with TEST: in test mode."""
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setattr(messaging.smtplib, "SMTP_SSL", _FakeSMTP)

    messaging.send_alert("Pavlof RSAM", "subj", "body", test=True)

    smtp = _FakeSMTP.instances[0]
    assert "Subject: TEST: subj" in smtp.sent["text"]


def test_send_alert_attaches_files(monkeypatch, smtp_env, tmp_path):
    """send_alert reads and attaches provided files to the message."""
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setattr(messaging.smtplib, "SMTP_SSL", _FakeSMTP)

    img = tmp_path / "figure.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    messaging.send_alert("Pavlof RSAM", "subj", "body", attachment=img)

    smtp = _FakeSMTP.instances[0]
    assert "filename=figure.jpg" in smtp.sent["text"]


# ---------------------------------------------------------------------------
# connect_mattermost
# ---------------------------------------------------------------------------
def test_connect_mattermost_builds_driver_and_logs_in(monkeypatch):
    """connect_mattermost constructs a Driver from env vars and calls login()."""
    monkeypatch.setenv("MATTERMOST_SERVER_URL", "mm.example")
    monkeypatch.setenv("MATTERMOST_USER_ID", "uid")
    monkeypatch.setenv("MATTERMOST_USER_PASS", "pw")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    captured = {}

    class _FakeDriver:
        def __init__(self, options):
            captured["options"] = options
            self.logged_in = False

        def login(self):
            self.logged_in = True

    import sys
    import types as _types

    fake_module = _types.ModuleType("mattermostdriver")
    fake_module.Driver = _FakeDriver
    monkeypatch.setitem(sys.modules, "mattermostdriver", fake_module)

    mm = messaging.connect_mattermost()

    assert captured["options"]["url"] == "mm.example"
    assert captured["options"]["login_id"] == "uid"
    assert captured["options"]["verify"] is True  # default when CA bundle unset
    assert mm.logged_in is True


# ---------------------------------------------------------------------------
# upload_mm_attachments
# ---------------------------------------------------------------------------
class _FakeFiles:
    def __init__(self, recorder):
        self._rec = recorder

    def upload_file(self, channel_id=None, files=None):
        self._rec.append((channel_id, files))
        return {"file_infos": [{"id": f"id-{len(self._rec)}"}]}


class _FakeMM:
    def __init__(self):
        self.uploads = []
        self.files = _FakeFiles(self.uploads)
        self.created_posts = []
        self.posts = self

    def create_post(self, options=None):
        self.created_posts.append(options)
        return {"id": f"post-{len(self.created_posts)}"}


def test_upload_mm_attachments_returns_file_ids(tmp_path):
    """upload_mm_attachments uploads each file and returns the resulting ids."""
    mm = _FakeMM()
    f1 = tmp_path / "a.jpg"
    f1.write_bytes(b"a")
    f2 = tmp_path / "b.jpg"
    f2.write_bytes(b"b")

    ids = messaging.upload_mm_attachments(mm, "chan", [f1, f2])

    assert ids == ["id-1", "id-2"]
    assert len(mm.uploads) == 2


def test_upload_mm_attachments_empty_when_no_attachment(tmp_path):
    """upload_mm_attachments returns [] and uploads nothing when attachment is None."""
    mm = _FakeMM()
    assert messaging.upload_mm_attachments(mm, "chan", None) == []
    assert mm.uploads == []


# ---------------------------------------------------------------------------
# post_mattermost — send=True paths (connect/upload/create mocked)
# ---------------------------------------------------------------------------
@pytest.fixture
def mm_env(monkeypatch):
    monkeypatch.setenv("MATTERMOST_DEFAULT_CHANNEL_ID", "default-chan")
    monkeypatch.setenv("MATTERMOST_TEST_CHANNEL_ID", "test-chan")
    monkeypatch.setenv("MATTERMOST_POST_URL", "mm.example")


def test_post_mattermost_posts_to_default_channel(monkeypatch, mm_env):
    """post_mattermost connects, posts to the default channel, and returns a URL."""
    mm = _FakeMM()
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    url = messaging.post_mattermost(config, "subj", "body", send=True)

    assert mm.created_posts[0]["channel_id"] == "default-chan"
    assert url == "mattermost://mm.example/post-1"


def test_post_mattermost_uses_config_channel_id(monkeypatch, mm_env):
    """post_mattermost uses config.mattermost_channel_id when present."""
    mm = _FakeMM()
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)

    config = SimpleNamespace(alarm_name="Pavlof RSAM", mattermost_channel_id="cfg-chan")
    messaging.post_mattermost(config, "subj", "body", send=True)

    assert mm.created_posts[0]["channel_id"] == "cfg-chan"


def test_post_mattermost_test_mode_uses_test_channel(monkeypatch, mm_env):
    """post_mattermost posts to the test channel and prefixes TEST: in test mode."""
    mm = _FakeMM()
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    messaging.post_mattermost(config, "subj", "body", send=True, test=True)

    post = mm.created_posts[0]
    assert post["channel_id"] == "test-chan"
    assert "TEST: subj" in post["message"]


def test_post_mattermost_retries_once_on_error(monkeypatch, mm_env):
    """post_mattermost retries create_post once after an exception."""
    mm = _FakeMM()
    calls = {"n": 0}

    def flaky_create_post(options=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        mm.created_posts.append(options)
        return {"id": "post-retry"}

    mm.create_post = flaky_create_post
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    url = messaging.post_mattermost(config, "subj", "body", send=True)

    assert calls["n"] == 2
    assert url == "mattermost://mm.example/post-retry"


def test_post_mattermost_fans_out_to_volcano_response_channel(monkeypatch, mm_env):
    """post_mattermost also posts to a volcano's response channel when configured."""
    mm = _FakeMM()
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)

    config = SimpleNamespace(
        alarm_name="Pavlof RSAM",
        mm_response_channels={"Pavlof": "pavlof-chan"},
    )
    messaging.post_mattermost(config, "subj", "body", send=True, volcano="Pavlof")

    channels = [p["channel_id"] for p in mm.created_posts]
    assert "default-chan" in channels
    assert "pavlof-chan" in channels


def test_post_mattermost_fans_out_to_extra_channel_ids(monkeypatch, mm_env):
    """post_mattermost posts the same message to any extra channel_ids."""
    mm = _FakeMM()
    monkeypatch.setattr(messaging, "connect_mattermost", lambda: mm)

    config = SimpleNamespace(alarm_name="Pavlof RSAM")
    messaging.post_mattermost(
        config, "subj", "body", send=True, channel_ids=["extra-1", "extra-2"]
    )

    channels = [p["channel_id"] for p in mm.created_posts]
    assert channels == ["default-chan", "extra-1", "extra-2"]
