# Alarm Workflow

An alarm run is config-driven: you point the `run-alarm` CLI at a config name, and the environment variables plus that config's `.yml` file supply everything else.

```bash
run-alarm <config_name> [-t/--time DATETIME] [--test] [--force] [--earthscope] [--mm] [--icinga] [--env-file]
```

`<config_name>` is the config filename in `CONFIGS_DIR`, given with or without the `.yml` extension (e.g. both `RSAM` and `RSAM.yml` run `config/RSAM.yml`).

Each invocation is a single, self-contained run. `run-alarm` first does the setup, locking, and dispatch shared by every alarm, then hands off to the module named by the config's `alarm_type`, which detects and classifies, and — only on a detection — fans the result out to email/SMS (and, optionally: Mattermost and Icinga). A typical cron fires one invocation every 1 to 5 minutes per config. The three stages below follow that order.

## 1. Setup and dispatch

Everything in this stage is identical across alarm types, so each module can assume a loaded environment, a configured logger, an exclusive lock, and a parsed config by the time its own code runs. The lock matters most under cron: since the same config fires every minute, it guarantees a slow run never overlaps the next invocation of the same alarm.

1. **Parse arguments** and resolve the processing time `T0` — the current UTC minute, or the `-t YYYYMMDDHHMM` timestamp if given.
2. **Load the environment** by searching up the directory tree for a `.env`, or from `--env-file`
3. **Configure logging** — rotating file logs under cron (if env var `FROMCRON=yep`), otherwise console output.
4. **Acquire a lock** (`LockFile`) so only one instance of a given config runs at a time. If the config is already locked, the run exits immediately.
5. **Load the config** and honor its kill switch: if `kill: true`, send a `WARNING` Icinga heartbeat and exit without running (if `--icinga` is set).
6. **Dispatch** by dynamically importing `volc_alarms.alarms.<alarm_type>` and calling its `run_alarm`, forwarding the `--test`, `--mm`, `--icinga`, and `--force` flags.
7. On any **uncaught error**, email a traceback to the `Error` recipients; the lock is always released and the elapsed time logged.

!!! note "Logging"
    If running from a cron and you want the output to be written to .log files, you must set:
    ```bash
    FROMCRON=yep
    ```
    in your environment (ideally in the crontab file)

## 2. Detect and classify

Each alarm module's `run_alarm` implements the type-specific logic (see [Alarm Modules](alarm-modules.md)), but the shape is consistent. This is where the alarms differ most: a seismic alarm filters and measures waveform amplitudes, a satellite alarm scrapes a feed, and so on. What they share is the final step — every run collapses its result into one of three monitoring states, and only a `CRITICAL` classification continues on to actually notify anyone. The `WARNING` and `OK` paths simply report a heartbeat (when `--icinga` is set) and stop.

1. **Acquire data** for the processing window — waveforms from Winston/Earthscope, or records from an FDSN event service or an external API/feed.
2. **Process and evaluate** the data against the config's thresholds and filters.
3. **Classify the result** into a monitoring state:
    - `CRITICAL` — a detection; proceed to the send sequence below.
    - `WARNING` — degraded or elevated (e.g. missing data, arrested, elevated-but-not-triggered).
    - `OK` — normal.

!!! note "Icinga"
    Icinga usage is optional, but when `--icinga` is set, the `OK`, `WARNING`,
    AND `CRITICAL` states are sent to Icinga to serve as heartbeat messages, which helps ensure the alarm is running on schedule as intended. Icinga is separately configured for its own alerting. At AVO, we set Icinga to alert per alarm after several missed heartbeats.

## 3. Send sequence (on a detection)

When a module classifies a run as `CRITICAL`, it calls the shared `run_send_sequence` (`utils/alarm_flow.py`), which runs these eight steps in order. Centralizing the sequence means every alarm notifies the outside world the same way, so figure handling, rate limiting, and recording behave identically no matter which module triggered. The ordering is deliberate: the rate-limit check comes first so a noisy source is suppressed before any figure is built or message sent, and recording the send happens before cleanup so later runs can see the alert for de-duplication. Figure and Mattermost steps are wrapped so a failure in either is logged but never blocks the email/SMS alert — getting the notification out takes priority over the extras.

1. **Rate-limit check** (`alarming.can_send`) — if the config opts into rate limiting (`alert_memory` + `max_alerts`) and the limit is hit, the alert is skipped, an Icinga heartbeat is sent, and the sequence returns early. See [Alarm Configuration → Rate limiting](alarm-configuration.md#rate-limiting).
2. **Build the figure** and output to `TMP_FIGURE_DIR`. A figure failure is logged but does not abort the alert.
3. **Create the message** — the module produces the alert `(subject, message)`. If this is the last alert before rate-limit suppression, a notice is appended.
4. **Post to Mattermost** (guarded) when `--mm` is set, with optional per-volcano channel routing. See [Alerting → Mattermost](alerting.md#mattermost).
5. **Send email/SMS** to the config's distribution list (resolved via `DISTRIBUTION_FILE` and `PHONEBOOK_FILE`).
6. **Record the send** to the SQLite database (`DB_FILE`) so rate limiting and de-duplication work on later runs.
7. **Clean up** (remove) the temporary figure file.
8. **Send the Icinga heartbeat** reporting the final state.

!!! note "Flag defaults"
    Mattermost (`--mm`) and Icinga (`--icinga`) are **off** unless their flags are passed. Running without them exercises the full detection logic while suppressing outbound chat posts and heartbeats — handy alongside `--test` (which uses test tables/channels and watermarks figures) and `--force` (which forces a trigger and implies `--test`).
