import math
import os
import time
import traceback
from zoneinfo import ZoneInfo

from volc_alarms.utils import alarming, messaging
from volc_alarms.utils.setup_utils import get_logger, _detect_system_tz

logger = get_logger(__name__)


def apply_cron_latency_backup(config, T0, extra_sleep=0.0):
    """Single shared implementation of the Cron_Latency_Backup block.

    Returns a (possibly adjusted) T0. Sleeps as a side effect when appropriate.

    - WHEN FROMCRON == "yep" and config.latency < 30:
        sleep(config.latency + extra_sleep), return T0 unchanged.
    - WHEN FROMCRON == "yep" and config.latency >= 30:
        return T0 - ceil(config.latency / 60) * 60 (no sleep).
    - OTHERWISE: return T0 unchanged, do not sleep.

    `extra_sleep` exists solely to preserve Tremor's existing behavior, which
    sleeps `config.latency + config.taper`. Infrasound and RSAM pass 0.0.
    """
    if os.getenv("FROMCRON") == "yep":
        if config.latency < 30:
            time.sleep(config.latency + extra_sleep)
        else:
            dt = math.ceil(config.latency / 60) * 60
            T0 = T0 - dt
            logger.info(f"Backing up {dt} seconds to align with minute marks")
    return T0


def run_send_sequence(
    config,
    T0,
    state,
    state_message,
    figure_factory,
    message_factory,
    *,
    can_send_kwargs=None,
    record_kwargs=None,
    mm_kwargs=None,
    send_email=True,
    mm_flag=True,
    icinga_flag=True,
    test_flag=False,
):
    """Single shared implementation of the CRITICAL Send_Sequence (Req 8).

      1. alarming.can_send rate-limit check
      2. figure creation via figure_factory(), guarded by try/except (Req 8.5)
      3. message creation via message_factory() -> (subject, message)
      4. messaging.post_mattermost, guarded by try/except
      5. messaging.send_alert (only when ``send_email`` is True)
      6. alarming.record_send
      7. os.remove(filename) if a file was produced
      8. messaging.icinga heartbeat

    Alarm-specific arguments are forwarded through can_send_kwargs and
    record_kwargs (e.g. Infrasound's volcano target name) (Req 8.6).
    ``mm_kwargs`` forwards extra keyword arguments to ``post_mattermost``
    (e.g. ``volcano`` for per-volcano channel routing). ``send_email``
    controls whether the email/SMS alert is sent (some alarms only email
    on force/urgent/test conditions).

    Returns the final state_message (so the caller can use it if needed).
    """
    can_send_kwargs = can_send_kwargs or {}
    record_kwargs = record_kwargs or {}
    mm_kwargs = mm_kwargs or {}

    # 1. Check rate limit
    if not alarming.can_send(config, T0=T0, test=test_flag, **can_send_kwargs):
        logger.warning(
            f"Rate limit: skipping alarm {config.alarm_name} "
            f"({config.max_alerts} alerts already sent within the last "
            f"{config.alert_memory} s)"
        )
        resumes_at = alarming.next_send_after(config, T0=T0, test=test_flag, **can_send_kwargs)
        if resumes_at:
            resumes_str = resumes_at.strftime("%H:%M UTC")
            logger.warning(f"Next alert allowed after {resumes_str}.")
        state_message = f"{state_message} (alarm skipped due to rate limit)"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return state_message

    # 2. Make figure
    try:
        filename = figure_factory()
    except Exception as e:
        logger.error("problem generating figure")
        logger.error(e)
        logger.error(traceback.format_exc())
        filename = None

    # 3. Create message
    subject, message = message_factory()

    # 3b. Annotate if this is the last alert before rate-limit suppression
    resumes_at = alarming.next_send_after(config, T0=T0, test=test_flag, **can_send_kwargs)
    if resumes_at:
        resumes_str = resumes_at.strftime("%H:%M UTC")
        local_tz = ZoneInfo(os.environ.get("TIMEZONE", _detect_system_tz()))
        resumes_local = resumes_at.astimezone(local_tz)
        resumes_local_str = resumes_local.strftime("%H:%M %Z")
        logger.info(
            f"Last alert for {config.alarm_name} before rate limit. "
            f"Next alert allowed after {resumes_str}."
        )
        message += (
            f"\n\n⚠️ Alert limit reached. No further alerts until after "
            f"{resumes_str} / {resumes_local_str}."
        )

    # 4. Post to mattermost (guarded)
    try:
        mm_url = messaging.post_mattermost(
            config, subject, message, attachment=filename, send=mm_flag, test=test_flag, **mm_kwargs
        )
        message = f"{message}\n\n{mm_url}"
    except Exception as e:
        logger.error("problem posting to mattermost")
        logger.error(e)
        logger.error(traceback.format_exc())

    # 5. Send email/sms if appropriate
    if send_email:
        messaging.send_alert(
            config.alarm_name, subject, message, attachment=filename, test=test_flag
        )

    # 6. Record alert send
    alarming.record_send(config, T0, test=test_flag, **record_kwargs)

    # 7. Cleanup
    if filename:
        os.remove(filename)

    # 8. Send icinga heartbeat
    messaging.icinga(config, state, state_message, send=icinga_flag)
    return state_message
