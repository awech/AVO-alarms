# Alerting

When an alarm triggers, `volc-alarms` can reach the outside world through three independent channels: **email/SMS**, **Icinga** heartbeats, and **Mattermost** posts. Email/SMS fires on every detection for most alarm modules; Icinga and Mattermost are opt-in per run via the `--icinga` and `--mm` flags. All three are driven from `utils/messaging.py` as part of the shared [send sequence](getting-started.md#3-send-sequence-on-a-detection).

## Email/SMS alerts

On a detection, the alarm emails its subject, body, and any figure attachments to the configured recipients (`messaging.send_alert`). SMS recipients are just email addresses at a carrier's SMS gateway, so the same path covers both. 

!!! Note "Some modules don't email"
    For most modules, email is **always** sent on a detection — there is no flag to toggle it. But some modules were designed to be for situational awareness only because of their less-actionable info, and thus only send alerts to mattermost (`Magnitude`, `Swarm`, `VAA`, `NOAA_CIMSS`). This is fine for AVO's current needs but should probably be handled via an optional `--no-email` flag in the future.

### How recipients are resolved

Recipient lists come from two YAML files (`messaging.get_recipients_list`):

- **`DISTRIBUTION_FILE`** maps an alarm (or group) to a list of user keys. The lookup order is:
    1. **Test mode** (`--test`): the `Test` group if present, otherwise the `Error` group.
    2. An entry whose header matches the alarm's `alarm_name`.
    3. The `All Alarms` group, used as the default when no alarm-specific entry exists.
- **`PHONEBOOK_FILE`** maps each user key to an actual email/SMS address. Users listed in the distribution file but missing from the phonebook are skipped with an error (no message sent to that user). The phonebook is sensitive and should **not** be committed to a public repo.

See `config/distribution.yml` and `config/phonebook.yml` for example formats of how distribution entries line up with alarm configs.

### Environment variables

| Variable            | Description                                              |
|---------------------|----------------------------------------------------------|
| `SMTP_IP`           | SMTP relay host/IP                                       |
| `SMTP_PORT`         | SMTP relay port                                          |
| `SMTP_SECURITY`     | `ssl` (implicit TLS, default) or `starttls`              |
| `DISTRIBUTION_FILE` | Path to the distribution-list YAML                       |
| `PHONEBOOK_FILE`    | Path to the phonebook YAML (user key → address)          |

The `From` address is derived from the alarm name (e.g. `Pavlof_RSAM@usgs.gov`). In test mode the subject is prefixed with `TEST:`.

## Icinga

Icinga integration is **opt-in**. Each alarm run can report a heartbeat to an [Icinga2](https://icinga.com/docs/icinga-2/latest/doc/01-about/) monitoring server so you can tell the difference between "the alarm ran and found nothing" and "the alarm stopped running", or "the alarm failed silently".

### How it works

When `run-alarm` is passed the `--icinga` flag, the alarm sends its final state to an Icinga2 service as a passive check result via the Icinga2 REST API (`actions/process-check-result`). The state maps to standard monitoring exit codes:

| State      | Exit code | Meaning                                              |
|------------|-----------|------------------------------------------------------|
| `OK`       | 0         | Alarm ran normally (detection or no detection)       |
| `WARNING`  | 1         | Degraded run — e.g. data-quality/latency issue, or the config kill switch is active |
| `CRITICAL` | 2         | Alarm triggered                     |
| `UNKNOWN`  | 3         | Hung or failed silently and stopped sending heartbeats |

### Environment variables

Add the following to your `.env` (see `.env_example`). All four are required when running with `--icinga`:

| Variable          | Description                                                        |
|-------------------|--------------------------------------------------------------------|
| `ICINGA_URL`      | Full URL to the Icinga2 `process-check-result` API endpoint        |
| `ICINGA_HOST_NAME`| Icinga host object the alarm services are attached to              |
| `ICINGA_USERNAME` | Icinga2 API user with permission to submit check results           |
| `ICINGA_PASSWORD` | Password for that API user                                         |

### Service naming

By default the alarm's `alarm_name` (from the alarm's config `.yml`) is used as the Icinga service name. To point an alarm at a differently named Icinga service, set `icinga_service_name` in the config:

```yaml
icinga_service_name: Pavlof RSAM heartbeat
```

### Enabling it on a cron

Add `--icinga` to the alarm invocation so the heartbeat is actually sent (it is off unless the flag is present):

```bash
* * * * * cd /path/to/dev-alarms && FROMCRON=yep run-alarm Pavlof_RSAM --icinga > /dev/null 2>&1
```

## Mattermost

Mattermost posting is **opt-in** and requires the AVO extras (`pip install -e .[avo]`, which pulls in `mattermostdriver`). When `run-alarm` is passed the `--mm` flag, a triggered alarm posts its subject, body, and any figure attachments to a Mattermost channel.

!!! note "Mattermost Fail"
    Failure to post to post to mattermost does not prevent Email/SMS/Icinga messages from sending.

### Environment variables

Add the following to your `.env` (see `.env_example`):

| Variable                        | Description                                               |
|---------------------------------|-----------------------------------------------------------|
| `MATTERMOST_SERVER_URL`         | Mattermost server hostname                                |
| `MATTERMOST_USER_ID`            | Login ID for the posting bot/user                         |
| `MATTERMOST_USER_PASS`          | Password for that user                                    |
| `MATTERMOST_TEAM_ID`            | Team the target channels belong to                        |
| `MATTERMOST_DEFAULT_CHANNEL_ID` | Channel that receives alarms with no channel override     |
| `MATTERMOST_POST_URL`           | Base URL used to build a permalink back to the post       |
| `MATTERMOST_TEST_CHANNEL_ID`    | Channel used when running with `--test` (optional)        |

TLS verification uses the standard `REQUESTS_CA_BUNDLE` variable honored by `requests` (which `mattermostdriver` wraps). If unset, it falls back to the default trust store (certifi).

### Channel routing

Posts resolve their destination channel in the following order:

1. **Test mode** (`--test`): posts to `MATTERMOST_TEST_CHANNEL_ID` and prefixes the subject with `TEST:`.
2. **Per-alarm override**: if the alarm config sets `mattermost_channel_id`, that channel is used instead of the default.
    ```yaml
    # in an alarm config .yml
    mattermost_channel_id: <channel_id>
    ```
3. **Default**: `MATTERMOST_DEFAULT_CHANNEL_ID`.



#### Per-volcano response channels

An alarm can fan out to a volcano-specific response channel in addition to its primary channel. Define a `mm_response_channels` mapping in the config; when the detection's volcano matches a key, the message is also posted there (skipped in test mode):

```yaml
mm_response_channels:
  Pavlof: <pavlof_channel_id>
  Veniaminof: <veniaminof_channel_id>
```

#### Additional ad-hoc channels

Some alarms route to extra channels (e.g. thermal or elevated-volcano channels) by passing a list of channel IDs at post time. These extra posts are also skipped in test mode.

### Message formatting

Alarm subjects and bodies are rendered into Mattermost markdown before posting (see `format_mm_message`). Figure attachments are uploaded first and referenced from the post. See the [API Reference](api-reference.md#volc_alarms.utils.messaging) for the underlying functions.


## Testing

Alarms send real notifications to real people, so you need a way to exercise the full detection and alerting path without paging the duty scientist or polluting the alert history. Three `run-alarm` flags exist for exactly that: `--test`, `--force`, and `--earthscope`. They are independent of the `--mm`/`--icinga` toggles and can be combined. pytest is great for checking logic and execution, but these flags allow the user to test alarm and config changes on real data and to test the full alerting pathway.

### `--test`

Runs the alarm end-to-end but routes everything to test destinations so a real detection is never confused with a drill. It changes behavior in several places:

- **Database:** reads and writes go to the `test_*` tables (`test_sent_events`, `test_swarm_table`, `test_tremor_table`) instead of production (`resolve_table_name`). Test runs therefore don't affect rate limiting, de-duplication, or the real alert history. Query them with `list-alerts --test`.
- **Email/SMS:** recipients resolve to the `Test` distribution group if it exists, otherwise the `Error` group — never the real alarm recipients. The subject is prefixed with `TEST:`.
- **Mattermost:** posts go to `MATTERMOST_TEST_CHANNEL_ID` (also prefixed `TEST:`), and the per-volcano and ad-hoc channel fan-out is skipped.
- **Figures:** the generated figure is watermarked `TEST` so it's obvious at a glance.

```bash
run-alarm Pavlof_RSAM --test -t 201701020205   # replay a known event into the test tables/channels
```

### `--force`

Forces a detection even when the data doesn't actually cross threshold — useful for verifying the full alert path (figure → message → post → email → record) end-to-end, or for confirming a newly configured alarm wires up correctly. **`--force` implies `--test`** (it sets `test=True` in `update_arguments`), so a forced run never touches production tables or recipients.

How "force" is applied is **alarm-specific** — each module relaxes whatever threshold or filter normally gates its detection. For example:

- **RSAM** sets the station minimum to zero (`min_sta = 0`) so any run trips the detection branch.
- **Infrasound** drops the amplitude threshold to zero (`min_pa = 0`), skips the channel-count gate, and evaluates only the first configured target (relaxing the per-target filters if nothing passes).

Most other modules behave similarly (e.g. Magnitude lowers its magnitude minimum; NOAA_CIMSS and VAA replay the most recent advisory). A few exceptions worth knowing:

- **Tremor** and **Swarm** accept the flag but don't act on it — forcing has no effect.
- **NOAA_CIMSS** and **VAA** only send email/SMS when forced; otherwise they post to Mattermost only.

```bash
run-alarm Pavlof_RSAM --force   # guaranteed detection; test mode is implied
```

### `--earthscope`

Switches waveform downloads from the configured waveserver (Winston, via `WINSTON_HOST`/`WINSTON_PORT`) to the [EarthScope](https://www.earthscope.org/) FDSN client. It sets the `USE_EARTHSCOPE` environment variable, which `downloading.download_waveforms` checks when choosing a client.

This matters because the local Winston typically only buffers a limited, recent window of data. To test or replay an **older** event — one that has aged out of the waveserver — point the alarm at EarthScope's archive instead:

```bash
run-alarm Pavlof_RSAM --test --earthscope -t 201701020205   # pull archived data for an old event
```

`--earthscope` only affects the seismic/acoustic alarms that download waveforms (RSAM, Infrasound, Tremor); alarms sourced from FDSN event services or external APIs are unaffected.
