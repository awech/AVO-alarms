# Tests
# Tests

This suite is organized so an unfamiliar reviewer can quickly see **what is
tested, where, and how**. It is split by *target* (which part of the package)
and then by *type* (unit vs integration).

## Two kinds of tests

| Type | Marker | What it does | How it mocks |
|------|--------|--------------|--------------|
| **Unit** | `@pytest.mark.unit` | Exercises a single function with crafted inputs and asserts its output/behavior. Fast and isolated. | Local mocking only — it mocks *just* the external calls the function under test makes (a download, SMTP/Mattermost client, FDSN client, `save_file`, etc.). Never touches the real network, database, or email. Matplotlib renders only headless (Agg), to a temp file where a function's job is to produce one. |
| **Integration** | `@pytest.mark.integration` | Drives a whole alarm's `run_alarm()` end to end and compares its observable behavior (Icinga state, Mattermost/email sends, DB writes, file cleanup, call order) to a frozen JSON baseline. | The shared **fakes harness** (`tests/_harness/`) replaces *every* external service at once. |

Run a slice:

```bash
pytest -m unit           # fast, isolated function tests
pytest -m integration    # full run_alarm() regression against baselines
pytest                   # everything
```

## Directory layout

```
tests/
├── README.md                       # this file (conventions + coverage matrix)
├── __init__.py
├── conftest.py                     # shared env setup + fixtures (unit + integration)
├── _harness/                       # shared integration machinery (NOT tests)
│   ├── fakes.py                    # CallRecorder, FakeAlarmDB, AlarmDoubles, install()
│   ├── snapshot_utils.py           # capture behavior + save/load baseline JSON
│   ├── scenarios.py                # per-alarm run_alarm scenario drivers
│   └── baselines/                  # frozen known-good JSON snapshots
│       └── <Alarm>/                # one subdir per alarm
│           └── <Alarm>-<variant>.json
├── utils/                          # unit tests for volc_alarms.utils.*
│   ├── test_alarming.py
│   ├── test_messaging.py
│   ├── test_processing.py
│   ├── test_plotting.py
│   ├── test_setup_utils.py
│   ├── test_downloading.py
│   └── test_alarm_flow.py
├── alarms/                         # one folder per alarm
│   ├── test_harness_smoke.py       # verifies the fakes/doubles themselves
│   └── <Alarm>/
│       ├── test_detection.py       # unit: detection.py logic
│       ├── test_message.py         # unit: message.py formatting
│       ├── test_figure.py          # unit: figure.py logic (save_file mocked)
│       └── test_run_alarm.py       # integration: scenario -> snapshot -> baseline
├── scripts/                        # unit tests for volc_alarms.scripts.* (one per CLI)
│   ├── test_run_alarm_cli.py
│   ├── test_dr_to_rsam_cli.py
│   ├── test_list_alerts_cli.py
│   ├── test_email_test_cli.py
│   ├── test_generic_alarm_cli.py
│   ├── test_update_metadata_cli.py
│   └── test_notification_html_cli.py
└── fixtures/                       # shared static data + crafted sample inputs
    ├── _record_*_event.py          # one-off recorders (Infrasound/RSAM/Tremor/Magnitude)
    ├── _build_tremor_grid.py       # one-off: build the Tremor travel-time grid fixture
    ├── configs/                    # test-only alarm configs (KENI_Infrasound, Pavlof_RSAM, Pavlof_tremor)
    └── data/                       # recorded events + metadata, e.g.:
        #   *.mseed        waveforms (Infrasound/RSAM/Tremor)
        #   *.csv          FDSN catalogs (Magnitude/Swarm) + PIREP shapefile zip
        #   *.json         API pulls (Lightning strokes, NOAA_CIMSS alerts)
        #   *.quakeml      per-event catalog (Magnitude)
        #   *.html / *.png NOAA_CIMSS alert page + images
        #   *.txt          VAA advisory text product
        #   station.xml / *_inv.xml  station metadata + responses
        #   Pavlof_Tremor_grid.npz   enveloc travel-time grid
```

### Baseline file naming

Frozen baselines live at `_harness/baselines/<Alarm>/<Alarm>-<variant>.json`. The
`-` separates the alarm module from the scenario variant so the name splits
unambiguously even though several module names (`NOAA_CIMSS`, `Pilot_Report`) and
variants (`not_enough_channels`, `ignored_volcano`) contain `_`. The scenario
registry key is exactly the `<Alarm>-<variant>` string; `SCENARIOS` maps it to a
`(module, driver)` tuple, and the module names the baseline subdir (so the path
is derived from an explicit field, never by parsing the name).

## Naming and docstring conventions

- **Files:** `test_<module>.py` for utils; `test_detection.py` / `test_message.py`
  / `test_figure.py` for an alarm's units; `test_run_alarm.py` for an alarm's
  integration test.
- **Test functions:** `test_<function>_<behavior>`, e.g.
  `test_process_polygons_parses_two_ring_field`.
- **Docstrings:** the first line names the function under test and the behavior
  being asserted. No references to bug-tracker IDs or spec requirement numbers.

## Updating integration baselines

When you deliberately change alarm behavior, the integration tests will fail
because the captured behavior no longer matches the frozen JSON. Regenerate and
review the diff before committing:

```bash
REGEN_BASELINES=1 pytest -m integration
git diff tests/_harness/baselines
```

## Coverage matrix

This maps each part of `volc_alarms` to the test(s) that exercise it. Legend:

- ✅ **unit** — has dedicated unit tests for its pure logic
- 🔄 **integration** — exercised end to end via the alarm's `run_alarm` baseline
  (and/or the harness smoke tests), not as isolated units
- N/A — no standalone unit-level logic to test (thin wrapper, or the whole
  behavior only makes sense end to end)

Every `run_alarm` pipeline has an integration baseline, but the baselines differ
in **how deep into the pipeline they reach** — see "Integration baseline depth"
below before relying on the alarms table. Unit tests focus on the pure logic
(parsing, math, thresholds, message formatting). The shared `utils/*` network,
messaging, and client boundaries are additionally unit-tested with local fakes
(see the utils table). Alarm-level `figure.py` rendering is still exercised via
the per-alarm figure smoke tests + integration rather than as isolated units.

### utils

| Module | Unit tests | Notes |
|--------|-----------|-------|
| `alarming` | ✅ `utils/test_alarming.py` | DB/rate-limit logic against a temp sqlite; operator CLI list/remove helpers left as TODO |
| `processing` | ✅ `utils/test_processing.py` | geodesy, volcano lookup, stream preprocessing; `Dr_to_RSAM` and `eq_picks_to_dataframe` are unit-tested with the FDSN/Earthscope client served offline from the test/Magnitude StationXML |
| `messaging` | ✅ `utils/test_messaging.py` | pure formatting + `send=False` short-circuits; the live send paths (`icinga`, `send_alert`, `connect_mattermost`, `upload_mm_attachments`, `post_mattermost`) are unit-tested with local `requests`/`smtplib`/Mattermost-driver fakes (no sockets) |
| `setup_utils` | ✅ `utils/test_setup_utils.py` | config parse, math-expr eval, path/tz detection, volcano-list loading, `load_environment`, `setup_root_logger`/`get_logger`, and `LockFile` |
| `plotting` | ✅ `utils/test_plotting.py` | pure geometry/tick math + the no-render helpers (`save_file`, `add_watermark`, `default_colormap`, `default_grid_params`, `time_ticks`, tile URL); cartopy GeoAxes rendering (`make_map`/spectrogram builders) is integration-only |
| `downloading` | ✅ `utils/test_downloading.py` | trace QC + HTTP retry wrappers (mocked `requests`); `download_waveforms`, `Earthscope_client`, and `download_station_xml` are unit-tested with faked FDSN/Winston clients + the NSLC-config helpers |
| `alarm_flow` | ✅ `utils/test_alarm_flow.py` | cron-latency backup + the shared CRITICAL send sequence (rate-limit skip, figure/post exception handling, send_email + kwargs forwarding) |

### alarms

| Alarm | detection | message | figure | run_alarm (integration depth) |
|-------|-----------|---------|--------|-------------------------------|
| Infrasound | ✅ | 🔄 | ✅ | 🟢 full send + ⚪ no-detect + 🟡 early-exit (all branches) |
| Lightning | ✅ | ✅ | ✅ | 🟢 full send + ⚪ distal/ignored/all-seen + 🟡 API error (all branches) |
| Magnitude | ✅ | 🔄 | ✅ | 🟢 full send + ⚪ no-op/not-near/already-processed + 🟡 FDSN error (all branches) |
| NOAA_CIMSS | ✅ | 🔄 | ✅ | 🟢 full send + ⚪ no-new/ignored/already-processed + 🟡 API/webpage error (all branches) |
| Pilot_Report | ✅ | 🔄 | ✅ | 🟢 full send (urgent + non-urgent) + ⚪ no-reports/already-processed + 🟡 API error (all branches) |
| RSAM | ✅ | ✅ | ✅ (shared builder) | 🟢 full send + ⚪ normal OK + 🟡 data-missing (all branches) |
| SO2 | ✅ (offline path) | ❌ | ❌ | 🟡 early-exit only — *excluded from coverage* (see note) |
| Swarm | ✅ | 🔄 | ✅ | 🟢 full send (single + multi-param + simultaneous) + ⚪ continuation-WARNING/no-swarm/not-near + 🟡 FDSN error (all branches) |
| Tremor | ✅ | 🔄 | ✅ (shared builder) | 🟢 full send + ⚪ normal OK + 🟡 data-missing (all branches) |
| VAA | ✅ | ✅ | ✅ | 🟢 full send + ⚪ no-advisories/already-processed + 🟡 webpage error (all branches) |

The `detection`/`message`/`figure` columns describe how each alarm's
`<Alarm>/{detection,message,figure}.py` is tested (unit tests live in
`tests/alarms/<Alarm>/test_*.py`). Every alarm has all three modules:

- ✅ — has a dedicated unit test.
- 🔄 — no dedicated unit test, but the module's code **actually runs** during the
  `run_alarm` integration baseline, so a crash there would be caught. For
  `message.py` this means the alarm reaches a send in some scenario (only the
  🟢 full-send alarms do), so its `create_message` executes.
- ❌ — **not tested at all.** For `message.py`, the alarm's baselines never reach
  a send (they resolve to a no-op OK or an early exit), so `create_message` never
  runs in integration and has no unit test. For `figure.py`, the integration
  scenarios stub out `make_figure`/`save_file` to avoid rendering, so figure
  builders are never exercised by integration either — a bug in one would go
  uncaught. RSAM and Tremor `figure.py` are thin wrappers over the shared
  spectrogram builder in `utils/plotting.py`; both have figure smoke tests that
  drive that shared builder (marked ✅ "shared builder").

> Figure tests (where present) are **smoke tests**: they confirm the figure
> builder runs end to end and returns a path — the failure mode that matters,
> since figure generation is wrapped in try/except in production — not that the
> output looks a certain way. See VAA `test_figure.py` (cartopy map), Lightning
> `test_figure.py` (cartopy map + time-colored stroke scatter), Magnitude
> `test_figure.py` (trace mosaic + response removal + map, from a recorded event),
> Infrasound `test_figure.py` (mosaic + spectrograms), NOAA_CIMSS
> `test_figure.py` (two alert images + map, with the recorded PNGs staged into
> TMP_DIR), and Pilot_Report `test_figure.py` (report map + flight-level caption);
> all fake the data/compute boundaries (`save_file`, downloads, and — for
> Magnitude — the Earthscope station-metadata client) and let the real plotting
> code run.

> **Coverage gotcha (cartopy + the default tracer).** Measuring figure coverage
> with coverage.py's default C tracer *understates* it: when cartopy's C
> extensions call back into Python, the tracer stops recording, so lines after
> the first `make_map` call execute but are not counted (e.g. Lightning
> `figure.py` reads as ~47% when it is actually 100%). Measure figure/cartopy
> code with the `sys.monitoring` tracer instead:
> `COVERAGE_CORE=sysmon coverage run -m pytest ...`.

#### Integration baseline depth (important)

The `run_alarm` column reports **how much of the pipeline the frozen baseline
actually reaches**, because this is uneven across alarms and the format alone
does not reveal it:

- 🟢 **full send** — the scenario feeds fixtures that trigger a real CRITICAL
  detection and the complete send sequence (figure → Mattermost → email → DB
  record → cleanup → Icinga). This is the strongest regression guard. Alarms:
  **RSAM**, **Lightning**, **Magnitude**, **NOAA_CIMSS**, **Pilot_Report**,
  **VAA**, **Swarm**, **Infrasound**, **Tremor** (all have a `critical` scenario).
  **Pilot_Report** additionally has a `non_urgent` send (same report, urgency
  flipped) that sends as a WARNING without the CRITICAL-only email. **Swarm** adds
  a `multi_param` send (one sequence caught by both DBSCAN parameter sets, deduped
  to a single alert) and a `simultaneous_swarms` send (two clusters at different
  volcanoes -> two alerts).
- ⚪ **no-detect / no-op OK / sub-threshold** — the decision logic fully runs but
  reaches a non-CRITICAL result: a "nothing to report" no-op the alarm is
  designed to produce (empty catalog / no new reports — **Swarm**, **Magnitude**
  representative, **Pilot_Report** `no_reports`/`already_processed`, **VAA**
  `no_advisories`/`already_processed`, **Swarm** `no_swarm`/`not_near_volcano`
  and `continuation` — the last a WARNING where new events extend a prior swarm
  from the DB without forming a fresh one); a real signal the detection logic
  evaluates and rejects (**Infrasound** `wrong_backazimuth`: a coherent airwave
  no target accepts; **Lightning** `distal`: a real storm whose strokes are all
  outside the inner ring, `ignored_volcano`: real proximal strokes at a volcano
  opted out via the ignore column, `all_seen`: strokes the DB already recorded;
  **Magnitude** `not_near_volcano`: a quake beyond the config distance from any
  volcano, `already_processed`: the recorded event whose id is already in the DB;
  **NOAA_CIMSS** `no_new_alerts`: alerts all beyond max_distance, `ignored_volcano`:
  an alert at a volcano opted out via the NOAA column, `already_processed`: an
  alert id already in the DB); or real data that lands below/around threshold
  (**RSAM**
  `elevated`/`arrested`/`normal`: the same recorded event scaled to the
  elevated-WARNING, arrestor-vetoed, and OK branches).
- 🟡 **early-exit only** — the scenario feeds no usable input, so the alarm bails
  at an input guard (missing data / not-enough-channels / API or webpage error)
  **before its detection logic runs**. These baselines verify the plumbing and
  the guard, **not** the science. Alarm with *only* this depth: **SO2** (which is
  also excluded from the coverage total — see the note below).
  (Note: **Infrasound**, **RSAM**, **Tremor**, **Lightning**, **Magnitude**,
  **NOAA_CIMSS**, **Pilot_Report**, **VAA**, and **Swarm** also have early-exit /
  API-error / FDSN-error / webpage-error / data-missing scenarios, but are not
  limited to that depth — they cover every branch.)

For the 🟡 alarm (**SO2**), the detection science is instead covered by the
`detection` unit tests (the SO2 parser). It has no end-to-end baseline and is
**excluded from the coverage total** (`[tool.coverage.run] omit` in
`pyproject.toml`): real SO2 detections are rare and ephemeral — the source
webpage only shows the current alert — so there is no historical page to record
as a fixture. Revisit when a live SO2 alert can be captured.

##### Record/replay pattern (how Infrasound and RSAM reach full coverage)

Both alarms replay ONE real recorded event, captured offline and committed as a
fixture, then steered down each `run_alarm` branch with a small config tweak:

- The raw waveforms were downloaded once via a `tests/fixtures/_record_*_event.py`
  recorder and saved as MiniSEED under `tests/fixtures/data/` (a KENI array event
  for Infrasound; Pavlof events for RSAM and Tremor).
- The scenarios feed that MiniSEED to the faked `download_waveforms`, so the real
  processing (LTS array inversion; RSAM RMS + reduced-displacement math; the
  enveloc location solver) runs deterministically with no network.
- Each scenario applies one config tweak (and, for Tremor, seeded prior DB state)
  to hit a different branch:
  - Infrasound: `not_enough_channels` (WARNING), `below_amplitude` (OK),
    `wrong_backazimuth` (OK, no detection), `critical` (CRITICAL send).
  - RSAM: `critical` (CRITICAL send, unmodified config), `elevated` and `normal`
    (thresholds scaled), `arrested` (arrestor threshold lowered), `data_missing`
    (channels zeroed).
  - Tremor: seven scenarios covering QC data-missing, normal OK, elevated,
    elevated-with-no-new-events, low-amplitude (RSAM-gate veto), missing
    rsam_station, and CRITICAL. Prior events are seeded into the tremor DB via
    the real `record_tremor_event_ids` so the "N events over T minutes"
    accumulation is exercised; the enveloc travel-time grid is a coarse
    precomputed `.npz` fixture (same extent as production, far fewer nodes).
- Station metadata lives in the test station XML and the per-alarm config under
  `tests/fixtures/configs/` (not the repo `config/`).

This record/replay recipe is the template for lifting the remaining 🟡 alarms.

##### Record/replay for API-JSON alarms (Lightning)

Lightning's input is JSON from the volcview "avorecent" API rather than
waveforms, so it uses the same record/replay idea with a different seam:

- A real API pull was pared to three single-storm fixtures under
  `tests/fixtures/data/` (`lightning_critical.json` — Edgecumbe proximal;
  `lightning_distal.json` — far Edgecumbe; `lightning_ignored.json` — proximal
  strokes at Behm Canal-Rudyerd Bay). One storm per file because `run_alarm`
  only trims strokes on the *lower* time bound (`time > T0 - duration`); in
  production the API returns just recent strokes, so there is no upper bound. Each
  scenario sets `T0` just after its storm's last stroke.
- The scenarios run the **real** `download_lightning` (captured at import before
  the harness doubles it) and fake only its `os.popen` curl call to return the
  fixture text, so the genuine parse + column-rename path runs. From there the
  normal cron path (`find_nearest_volcano` against the volcano list) executes.
- `VOLCANO_LIST` is pointed at the shipped `volcano_list_avo.csv`, which carries
  the per-alarm `Lightning` opt-out column (`Y`/`N`). The packaged
  `volcano_list.csv` placeholder omits that column, so the ignore path would be a
  no-op with it. The `ignored_volcano` scenario is the explicit proof the ignore
  works: strokes the API attributes to an `N` volcano are reassigned to the
  nearest `Y` volcano and dropped past `dist2`, yielding zero new strokes.
- The DB-state branches (`all_seen`) do not need a fixture — they drive the
  `filter_dataframe` double with a callable that reports every id as already
  seen, modelling the alarm-history DB suppressing a re-alert. (The double
  accepts either a fixed `(new_df, df)` tuple or such a callable, since Lightning
  calls `filter_dataframe` twice — the full set, then per volcano.)

##### Record/replay for a catalog + waveform alarm (Magnitude)

Magnitude's input is an FDSN earthquake catalog plus, for the figure, waveforms
and station metadata. The detection/message and the figure render are split
across the integration test and `test_figure.py`:

- Four fixtures under `tests/fixtures/data/` capture a real M3.25 event near
  Denison (2026-01-04): `..._..csv` (the FDSN hypocenters row), `..._..quakeml`
  (the per-event QuakeML with 68 picks / 41 stations), `..._..mseed` (70 s
  waveforms for the nearest 10 BHZ channels), and `..._.._inv.xml` (StationXML:
  coords for all 41 pick stations + full responses for the 10 recorded channels,
  pared to the event epoch — see `_record_magnitude_event.py`).
- The **integration** scenarios (`critical`, `already_processed`) feed the CSV +
  QuakeML to the faked downloaders and stub `plot_event`, so `run_alarm` runs the
  real `find_nearest_volcano` (places the event ~4.7 km from Denison, inside the
  10 km config distance) + `create_message` (rendered from the real picks) + the
  send/record/cleanup sequence — without rendering.
- The **figure** smoke test (`test_figure.py`) owns the full `plot_event` render:
  it serves the MiniSEED to `download_waveforms` and points a small
  local-inventory client (backed by the StationXML) at both `Earthscope_client`
  call sites, so `eq_picks_to_dataframe`'s per-station coord lookups and
  `st.remove_response` run offline while the real mosaic + map draw.
- `already_processed` seeds the recorded event id into the real (non-test)
  `sent_events` table via `alarming.get_conn`, so `run_alarm`'s `already_processed`
  sqlite check short-circuits to the "Old event detected" OK branch. `fdsn_error`
  uses the `hypocenter_csv_error` doubles knob to make the CSV downloader return
  `None`; `not_near_volcano` feeds a crafted offshore quake.

##### Record/replay for a scraped-page alarm (NOAA_CIMSS)

NOAA_CIMSS pulls an alert list from the volcview API, then scrapes each alert's
detail page (behind a login) and downloads its images. All three are recorded:

- Fixtures under `tests/fixtures/data/`: `noaa_cimss_vvapi.json` (a real 100-alert
  API pull) and `noaa_cimss_vvapi_spurr.json` (pared to the one Spurr ash alert,
  report 448880); `noaa_cimss_alert_448880.html` (the scraped detail page); and
  two downscaled alert PNGs.
- The `critical` / `webpage_error` / `already_processed` scenarios run the **real**
  `download_cimss_vv_api` (os.popen faked to serve the JSON) so the genuine
  `pd.read_json` + `format_cimss_dataframe` + `find_nearest_volcano` +
  `check_ignore_volcano` path runs, then return a `BeautifulSoup` of the recorded
  HTML from the `scrape_cimss_alert` double so the **real** `process_alert_soup`
  parsing runs (instrument, timestamp+radiative-center match, status/type, aid,
  image links). `get_cimss_image` is a harness no-op and `plot_fig` is stubbed;
  the render is covered by `test_figure.py`, which stages the two recorded PNGs
  into `TMP_DIR` where `plot_fig` reads them.
- `ignored_volcano` points `VOLCANO_LIST` at `volcano_list_avo.csv` and feeds a
  crafted alert on Tana (NOAA=N there), so `check_ignore_volcano` drops it -> OK:
  the explicit proof the NOAA opt-out column works. `already_processed` seeds the
  alert id into the real `sent_events` table; `api_error` / `no_new_alerts` use
  crafted download returns.

##### Record/replay for a shapefile alarm (Pilot_Report)

Pilot_Report downloads a zipped ESRI **shapefile** of pilot reports from the
Iowa State mesonet archive, then parses and filters it:

- One fixture under `tests/fixtures/data/`:
  `pilot_report_Shishaldin_20260911T0039.zip` — a real PIREP shapefile ZIP for a
  Shishaldin volcanic-ash report (2026-09-11 00:39 UTC), pulled with the same
  URL `download_pilot_reports` builds.
- The `critical` / `non_urgent` / `already_processed` scenarios return
  `("OK", <real ZipFile>)` from the `download_pilot_reports` double, so the real
  `pirep_archive_to_dataframe` (shapefile read), `find_nearest_volcano`
  (`filter_col="PIREP"`), and `check_volcano_mention` (the `VA SHISHALDIN`
  trigger) all run. `plot_fig` is stubbed; the render is covered by
  `test_figure.py`.
- `critical` keeps the report's real `URGENT='T'` → CRITICAL + email; `non_urgent`
  wraps `pirep_archive_to_dataframe` to set `URGENT='F'` on the parsed rows → the
  same report sends as a WARNING with no email, exercising the non-urgent branch.
- `VOLCANO_LIST` points at `volcano_list_avo.csv` because it carries the `PIREP`
  opt-in column (the packaged placeholder lacks it). `already_processed` seeds the
  report's event id into the real `sent_events` table; `api_error` returns
  `("WARNING", None)`, `no_reports` returns `("OK", None)`.

##### Record/replay for a text-product alarm (VAA)

VAA downloads a list of advisory links, then fetches and parses each advisory's
NWS text product:

- One fixture under `tests/fixtures/data/`:
  `vaa_Sheveluch_20260928T1753.txt` — a real Anchorage-VAAC Sheveluch eruption
  advisory (2026-09-28 17:53 UTC).
- The `critical` / `already_processed` scenarios return the advisory's text_link
  from the `download_mesonet_vaa_list` double and fake `fetch_vaa_page` to serve
  the recorded advisory text, so the real `process_vaa_id` (parse_vaa_fields,
  text_to_latlon, parse_vaa_dtg) + find_nearest_volcano + create_message all run.
  `make_map` is stubbed; the render is covered by the (pre-existing) test_figure.py.
- `already_processed` seeds the advisory id into the real `sent_events` table;
  `webpage_error` returns None (list download failed); `no_advisories` returns an
  empty text_link list. VOLCANO_LIST is pinned to `volcano_list_avo.csv` for
  determinism.

> Unlike the other alarms, VAA's unit layer (detection/message/figure) was
> already thorough — it was the original template for that split. The work here
> was the missing `run_alarm` record/replay layer, which lifted run_alarm from
> ~39% (webpage-error path only) to ~95%.

##### Record/replay for a clustering alarm (Swarm)

Swarm clusters an FDSN earthquake catalog (DBSCAN over space + time, with two
parameter sets — a 1 h "short" and a 24 h "long") and has the richest branch set:
a CRITICAL per detected swarm, a WARNING when new events merely *continue* a prior
swarm held in the `swarm_table` DB, plus the no-swarm / not-near / error paths.
It mixes one real fixture with two synthetic ones:

- `swarm_Makushin_20260923.csv` — a real Makushin swarm (pared to the
  near-volcano events), which clusters via the long params -> `critical`.
- `swarm_multi_param_synthetic.csv` — a crafted sequence that satisfies BOTH
  parameter sets; `get_swarms` returns a detection from each and `compare_swarms`
  collapses the overlapping pair to one alert (`multi_param`).
- `swarm_simultaneous_synthetic.csv` — two spatially separate crafted clusters
  (near Spurr and Redoubt), each its own swarm -> two CRITICAL sends
  (`simultaneous_swarms`). Real catalogs rarely contain two simultaneous swarms,
  so this path needed synthetic data.
- `continuation` seeds a near-complete prior swarm into `swarm_table` (via the
  real `record_swarm_event_ids`) and feeds a couple of new events that extend it;
  `check_swarm_continue` merges old+new and reports the ongoing-swarm WARNING.

The scenarios feed the CSV to the `download_hypocenters_csv` double **shaped the
way the real downloader returns it** — `id` renamed to `event_id` and times made
tz-naive via `UTCDateTime(...).strftime()` + `pd.to_datetime` — because
`get_swarms` compares the `time` column against a naive string; a plain tz-aware
`pd.to_datetime` would raise. `make_figure` is stubbed (render in `test_figure.py`,
which fakes the per-event hypocenter-XML download to an empty catalog).

> **Bug found + fixed by the simultaneous_swarms scenario.** `compare_swarms`
> (which dedups overlapping/duplicate swarms when 2+ are detected) merged on a
> non-existent `id` column (`on=["id","id"]`) and read a non-existent `.Time` —
> real `run_alarm` data carries `event_id`/`time`. Any run detecting 2+
> overlapping swarms would have raised; single-swarm runs skip that merge, and the
> old unit test crafted DataFrames with `id`/`Time` columns that masked it. Fixed
> to `on="event_id"` and `.time`; the unit test now uses the real column names and
> `simultaneous_swarms` guards it end to end.

#### Extending coverage (known follow-ups)

- **SO2** (blocked): apply the record/replay pattern once a live SO2 alert page
  can be captured. It's a scraped/HTML alarm like NOAA_CIMSS/VAA, but its source
  only serves the current alert, so there's no historical fixture to record yet.
  Excluded from the coverage total until then.
- The FDSN/Winston-backed `utils` helpers (`Dr_to_RSAM`, `eq_picks_to_dataframe`,
  `download_waveforms`, `download_station_xml`) and the live messaging senders now
  have dedicated unit tests with local client/HTTP fakes.
- `utils/plotting.py` cartopy GeoAxes renderers (`make_map`, `add_volcanoes_to_map`,
  the `map_ticks` gridliner, the spectrogram builders) remain render-only, covered
  by the per-alarm figure tests; a mocked-tile unit test for `make_map` is a
  possible follow-up if `tests/utils`-scoped coverage of them is wanted.

### scripts

| Script | Unit tests | Notes |
|--------|-----------|-------|
| `run_alarm.py` | ✅ `scripts/test_run_alarm_cli.py` | arg parsing, time defaulting, cron/lock/kill-switch/dispatch/error branches |
| `dr_to_rsam.py` | ✅ `scripts/test_dr_to_rsam_cli.py` | arg validation (--config vs --nslc/--volcano) + Dr_to_RSAM dispatch |
| `list_alerts.py` | ✅ `scripts/test_list_alerts_cli.py` | start/end/duration validation, query-dict assembly, filtered_list dispatch |
| `email_test.py` | ✅ `scripts/test_email_test_cli.py` | lock-held return; sends a "Test" alert on the happy path |
| `generic_alarm.py` | ✅ `scripts/test_generic_alarm_cli.py` | lock-held return; sets the alarm's Icinga service to OK |
| `update_metadata.py` | ✅ `scripts/test_update_metadata_cli.py` | lock-held return; refreshes the station XML |
| `notification_html.py` | ✅ `scripts/test_notification_html_cli.py` | lock-held return; renders the distribution table to HTML |

All script tests mock the lock, logging, env loading, and the network/messaging
boundary, so no real lock file, email, Icinga call, or download occurs.
