"""Reusable test doubles for the alarm behavior-preservation harness.

This module provides the shared, side-effect-free stand-ins that let an alarm's
``run_alarm`` be driven offline and deterministically (Req 12.1). Every external
side effect an alarm performs is replaced:

* ``downloading.download_waveforms`` / ``download_hypocenters_csv`` /
  ``download_hypocenter_xml`` and the per-alarm ``download_*`` functions
  (``download_lightning``, ``download_cimss_vv_api``, ``download_pilot_reports``,
  ``scrape_cimss_alert``, ``get_cimss_image``, ``download_mesonet_vaa_list``,
  ``download_SO2``) -> return canned fixtures.
* ``messaging.post_mattermost`` / ``send_alert`` / ``icinga`` -> record the call
  (args + invocation order), perform no I/O.
* ``alarming.can_send`` / ``record_send`` / ``filter_dataframe`` -> backed by an
  in-memory store; record the call.
* figure builders / ``plotting.save_file`` -> return a sentinel path.
* ``os.remove`` -> record the call (no filesystem mutation).

The doubles share a single :class:`CallRecorder` so the *ordering* of calls
across modules is captured on one timeline. This is what the golden behavior
tests (task 1.2) and the send-sequence ordering tests (task 2.4) assert against.

Doubles read their configurable return values from the :class:`AlarmDoubles`
handle *at call time*, so a test can flip ``doubles.can_send_result = False`` (or
swap ``doubles.waveform_factory``) before invoking ``run_alarm``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from obspy import Catalog, Stream, Trace
from pandas import DataFrame


# ---------------------------------------------------------------------------
# Call recording
# ---------------------------------------------------------------------------
@dataclass
class Call:
    """A single recorded invocation of a doubled function."""

    name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Call(name={self.name!r}, args={self.args!r}, kwargs={self.kwargs!r})"


class CallRecorder:
    """Ordered log of calls made to the doubled functions.

    A single instance is shared by every double for a given test so that the
    relative ordering of, e.g., ``can_send`` -> ``post_mattermost`` ->
    ``send_alert`` -> ``record_send`` -> ``os.remove`` -> ``icinga`` can be
    asserted on one timeline (Req 8.3).
    """

    def __init__(self) -> None:
        self.calls: list[Call] = []

    def record(self, name: str, args: tuple = (), kwargs: dict | None = None) -> None:
        self.calls.append(Call(name, args, kwargs or {}))

    # -- queries -----------------------------------------------------------
    def names(self) -> list[str]:
        """Return the ordered list of recorded call names."""
        return [c.name for c in self.calls]

    def of(self, name: str) -> list[Call]:
        """Return every recorded call matching ``name`` (in order)."""
        return [c for c in self.calls if c.name == name]

    def first(self, name: str) -> Call | None:
        matches = self.of(name)
        return matches[0] if matches else None

    def last(self, name: str) -> Call | None:
        matches = self.of(name)
        return matches[-1] if matches else None

    def called(self, name: str) -> bool:
        return any(c.name == name for c in self.calls)

    def index(self, name: str) -> int:
        """Return the index of the first call to ``name`` (or -1)."""
        for i, c in enumerate(self.calls):
            if c.name == name:
                return i
        return -1

    def reset(self) -> None:
        self.calls.clear()


# ---------------------------------------------------------------------------
# Canned-fixture builders
# ---------------------------------------------------------------------------
def make_stream(nslc_list, T1, T2, *, sampling_rate: float = 100.0, data_fn=None) -> Stream:
    """Build a deterministic obspy :class:`~obspy.Stream` for ``nslc_list``.

    Mirrors the shape ``downloading.download_waveforms`` returns: one trace per
    NSLC string, gap-free, spanning ``T1``..``T2``. ``data_fn(npts, i, nslc)``
    may be supplied to inject non-zero data; the default is all zeros.
    """
    st = Stream()
    npts = max(int(round((T2 - T1) * sampling_rate)), 1)
    for i, nslc in enumerate(nslc_list):
        net, sta, loc, chan = nslc.split(".")
        if data_fn is None:
            data = np.zeros(npts, dtype="float64")
        else:
            data = np.asarray(data_fn(npts, i, nslc), dtype="float64")
        tr = Trace(data=data)
        tr.stats.network = net
        tr.stats.station = sta
        tr.stats.location = loc
        tr.stats.channel = chan
        tr.stats.sampling_rate = sampling_rate
        tr.stats.starttime = T1
        st += tr
    return st


def default_stream_factory(nslc_list, T1, T2, fill_value=0, iris=False, **_) -> Stream:
    """Default ``download_waveforms`` replacement: zero-filled traces."""
    return make_stream(nslc_list, T1, T2)


def empty_catalog(*_args, **_kwargs) -> Catalog:
    """Default hypocenter-XML replacement: an empty obspy Catalog."""
    return Catalog()


def empty_hypocenter_df(*_args, **_kwargs) -> DataFrame:
    """Default hypocenter-CSV replacement: an empty events DataFrame."""
    return DataFrame(
        columns=[
            "time",
            "latitude",
            "longitude",
            "depth",
            "mag",
            "event_id",
        ]
    )


# ---------------------------------------------------------------------------
# In-memory alarm-history store (replaces sqlite DB access)
# ---------------------------------------------------------------------------
class FakeAlarmDB:
    """In-memory stand-in for the sqlite alarm-history database.

    Backs the ``can_send`` / ``record_send`` / ``filter_dataframe`` doubles so
    no real database file is touched. Recorded sends are kept as plain dicts so
    golden tests can assert the ``alarm_id``, ``volcano``, ``event_id`` and
    processed-time fields (Req 9.4).
    """

    def __init__(self) -> None:
        self.records: list[dict] = []

    def record_send(self, config, T0, volcano=None, event_id=None, test=False) -> None:
        # Mirror the real record_send field-resolution logic so captured rows
        # match the production schema.
        if hasattr(config, "VOLCANO_NAME"):
            volcano = config.VOLCANO_NAME
        event_ids = event_id if isinstance(event_id, list) else [event_id]
        for ev_id in event_ids:
            self.records.append(
                {
                    "alarm_id": config.alarm_name,
                    "volcano": volcano,
                    "event_id": ev_id,
                    "process_time": T0,
                    "test": test,
                }
            )

    @property
    def sent_alarm_ids(self) -> list[str]:
        return [r["alarm_id"] for r in self.records]


# ---------------------------------------------------------------------------
# The doubles handle
# ---------------------------------------------------------------------------
class AlarmDoubles:
    """Configurable handle wiring the shared doubles together.

    A test tweaks the public knobs *before* driving ``run_alarm``:

    * ``waveform_factory`` -- callable building the canned waveform Stream.
    * ``hypocenter_csv`` / ``hypocenter_xml`` -- canned download returns.
    * ``can_send_result`` -- bool returned by the ``can_send`` double (Req 8.4).
    * ``filter_dataframe_result`` -- optional ``(new_df, df)`` override.
    * ``mm_url`` -- the sentinel URL returned by the ``post_mattermost`` double.
    * ``sentinel_figure`` -- the sentinel path returned by figure doubles.
    * ``download_returns`` -- per-name canned returns for the relocated
      ``download_*`` / scrape functions.

    Inspect results afterward via ``recorder`` (ordering + args) and ``db``
    (recorded sends).
    """

    def __init__(self, recorder: CallRecorder, db: FakeAlarmDB, monkeypatch) -> None:
        self.recorder = recorder
        self.db = db
        self.monkeypatch = monkeypatch

        # --- configurable knobs ---------------------------------------
        self.waveform_factory: Callable[..., Stream] = default_stream_factory
        self.hypocenter_csv: Any = None
        self.hypocenter_xml: Any = None
        self.can_send_result: bool = True
        self.filter_dataframe_result: Any = None
        self.mm_url: str = "mattermost://test-server/post-id"
        self.sentinel_figure: Path = Path("tmp_files") / "__sentinel_figure__.jpg"

        # Canned returns for the per-alarm download / scrape helpers. Defaults
        # are benign "no new data" values; a test overrides as needed.
        self.download_returns: dict[str, Any] = {
            "download_lightning": None,
            "download_cimss_vv_api": None,
            "download_pilot_reports": ("OK", None),
            "scrape_cimss_alert": None,
            "get_cimss_image": None,
            "download_mesonet_vaa_list": None,
            "download_SO2": (None, None),
        }

    # -- convenience pass-throughs -------------------------------------
    @property
    def calls(self) -> list[Call]:
        return self.recorder.calls

    def call_names(self) -> list[str]:
        return self.recorder.names()

    # -- figure-builder patching ---------------------------------------
    def patch_figure_builder(self, module, name: str = "make_figure"):
        """Replace an alarm's figure builder with a sentinel-returning double.

        Avoids running matplotlib entirely. The double records the call (under
        ``"<name>"``) and returns ``self.sentinel_figure``.
        """

        def _figure_double(*args, **kwargs):
            self.recorder.record(name, args, kwargs)
            return self.sentinel_figure

        self.monkeypatch.setattr(module, name, _figure_double)
        return _figure_double

    def patch_callable(self, module, name: str, double: Callable):
        """Repoint an arbitrary ``module.name`` to ``double``.

        Useful once functions are relocated into alarm packages (later tasks):
        the same double can be installed at its new home.
        """
        self.monkeypatch.setattr(module, name, double)


# ---------------------------------------------------------------------------
# Installation: patch every external side effect onto the canonical modules
# ---------------------------------------------------------------------------
def install(handle: AlarmDoubles) -> AlarmDoubles:
    """Patch all doubled functions onto their canonical ``utils`` modules.

    Patches attributes on the module objects (alarms call e.g.
    ``messaging.post_mattermost`` via the imported module, so attribute patching
    is sufficient). ``os.remove`` is patched on the ``os`` module for the test's
    duration; monkeypatch reverts it afterward.
    """
    from avo_alarms.utils import alarming, downloading, messaging, plotting

    rec = handle.recorder
    mp = handle.monkeypatch

    # --- messaging (record only, no I/O) ------------------------------
    def _post_mattermost(config, subject, body, attachment=None, send=False, test=False, volcano=None):
        rec.record(
            "post_mattermost",
            (config, subject, body),
            {"attachment": attachment, "send": send, "test": test, "volcano": volcano},
        )
        return handle.mm_url

    def _send_alert(alarm_name, subject, body, attachment=None, test=False):
        rec.record(
            "send_alert",
            (alarm_name, subject, body),
            {"attachment": attachment, "test": test},
        )

    def _icinga(config, state, state_message, send=True):
        rec.record("icinga", (config, state, state_message), {"send": send})

    mp.setattr(messaging, "post_mattermost", _post_mattermost)
    mp.setattr(messaging, "send_alert", _send_alert)
    mp.setattr(messaging, "icinga", _icinga)

    # --- alarming (in-memory DB) --------------------------------------
    def _can_send(config, volcano="*", T0=None, test=False):
        rec.record("can_send", (config,), {"volcano": volcano, "T0": T0, "test": test})
        return handle.can_send_result

    def _record_send(config, T0, volcano=None, event_id=None, test=False):
        rec.record(
            "record_send",
            (config, T0),
            {"volcano": volcano, "event_id": event_id, "test": test},
        )
        handle.db.record_send(config, T0, volcano=volcano, event_id=event_id, test=test)

    def _filter_dataframe(df, id_column="id", test=False, table=None):
        rec.record("filter_dataframe", (df,), {"id_column": id_column, "test": test, "table": table})
        if handle.filter_dataframe_result is not None:
            return handle.filter_dataframe_result
        # Default: nothing previously seen -> every row is "new".
        return df.copy(), df

    mp.setattr(alarming, "can_send", _can_send)
    mp.setattr(alarming, "record_send", _record_send)
    mp.setattr(alarming, "filter_dataframe", _filter_dataframe)

    # --- downloading: shared waveform / hypocenter fetchers -----------
    def _download_waveforms(nslc_list, T1, T2, fill_value=0, iris=False):
        rec.record(
            "download_waveforms",
            (nslc_list, T1, T2),
            {"fill_value": fill_value, "iris": iris},
        )
        return handle.waveform_factory(nslc_list, T1, T2, fill_value=fill_value, iris=iris)

    def _download_hypocenters_csv(URL):
        rec.record("download_hypocenters_csv", (URL,))
        if handle.hypocenter_csv is not None:
            return handle.hypocenter_csv
        return empty_hypocenter_df()

    def _download_hypocenter_xml(URL):
        rec.record("download_hypocenter_xml", (URL,))
        if handle.hypocenter_xml is not None:
            return handle.hypocenter_xml
        return empty_catalog()

    mp.setattr(downloading, "download_waveforms", _download_waveforms)
    mp.setattr(downloading, "download_hypocenters_csv", _download_hypocenters_csv)
    mp.setattr(downloading, "download_hypocenter_xml", _download_hypocenter_xml)

    # --- downloading: per-alarm download / scrape helpers -------------
    # These currently live in ``downloading``; later tasks relocate them into
    # the owning alarm package, at which point ``handle.patch_callable`` can
    # reinstall the same double at its new home.
    def _make_download_double(fn_name):
        def _double(*args, **kwargs):
            rec.record(fn_name, args, kwargs)
            return handle.download_returns.get(fn_name)

        return _double

    for fn_name in (
        "download_lightning",
        "download_cimss_vv_api",
        "download_pilot_reports",
        "scrape_cimss_alert",
        "get_cimss_image",
        "download_mesonet_vaa_list",
        "download_SO2",
    ):
        if hasattr(downloading, fn_name):
            mp.setattr(downloading, fn_name, _make_download_double(fn_name))

    # --- relocated download helpers: also patch at new homes ----------
    # Functions that have been moved into alarm-package detection modules
    # must be patched there as well (the alarm imports from .detection).
    from avo_alarms.alarm_codes import VAA as vaa_pkg
    from avo_alarms.alarm_codes.VAA import detection as vaa_detection

    _vaa_double = _make_download_double("download_mesonet_vaa_list")
    mp.setattr(vaa_detection, "download_mesonet_vaa_list", _vaa_double)
    mp.setattr(vaa_pkg, "download_mesonet_vaa_list", _vaa_double)

    from avo_alarms.alarm_codes import Pilot_Report as pirep_pkg
    from avo_alarms.alarm_codes.Pilot_Report import detection as pirep_detection

    _pirep_download_double = _make_download_double("download_pilot_reports")
    mp.setattr(pirep_detection, "download_pilot_reports", _pirep_download_double)
    mp.setattr(pirep_pkg, "download_pilot_reports", _pirep_download_double)

    from avo_alarms.alarm_codes import Lightning as lightning_pkg
    from avo_alarms.alarm_codes.Lightning import detection as lightning_detection

    _lightning_double = _make_download_double("download_lightning")
    mp.setattr(lightning_detection, "download_lightning", _lightning_double)
    mp.setattr(lightning_pkg, "download_lightning", _lightning_double)

    from avo_alarms.alarm_codes import SO2 as so2_pkg
    from avo_alarms.alarm_codes.SO2 import detection as so2_detection

    _so2_double = _make_download_double("download_SO2")
    mp.setattr(so2_detection, "download_SO2", _so2_double)
    mp.setattr(so2_pkg, "download_SO2", _so2_double)

    from avo_alarms.alarm_codes import NOAA_CIMSS as cimss_pkg
    from avo_alarms.alarm_codes.NOAA_CIMSS import detection as cimss_detection

    _cimss_vv_double = _make_download_double("download_cimss_vv_api")
    mp.setattr(cimss_detection, "download_cimss_vv_api", _cimss_vv_double)
    mp.setattr(cimss_pkg, "download_cimss_vv_api", _cimss_vv_double)

    _cimss_scrape_double = _make_download_double("scrape_cimss_alert")
    mp.setattr(cimss_detection, "scrape_cimss_alert", _cimss_scrape_double)
    mp.setattr(cimss_pkg, "scrape_cimss_alert", _cimss_scrape_double)

    _cimss_image_double = _make_download_double("get_cimss_image")
    mp.setattr(cimss_detection, "get_cimss_image", _cimss_image_double)
    mp.setattr(cimss_pkg, "get_cimss_image", _cimss_image_double)

    # --- plotting: save_file returns a sentinel path ------------------
    def _save_file(fig, config, test=False, dpi=250):
        rec.record("save_file", (config,), {"test": test, "dpi": dpi})
        return handle.sentinel_figure

    mp.setattr(plotting, "save_file", _save_file)

    # --- os.remove: record the cleanup call (no fs mutation) ----------
    def _os_remove(path, *args, **kwargs):
        rec.record("os.remove", (path,))

    mp.setattr(os, "remove", _os_remove)

    return handle
