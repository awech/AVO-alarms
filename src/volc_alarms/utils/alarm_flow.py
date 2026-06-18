import math
import os
import time
import traceback
from volc_alarms.utils.setup_utils import get_logger
from volc_alarms.utils import messaging, alarming

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
    mm_flag=True,
    icinga_flag=True,
    test_flag=False,
):
    """Single shared implementation of the CRITICAL Send_Sequence (Req 8).

    Performs, in order (Req 8.3):
      1. alarming.can_send rate-limit check
      2. figure creation via figure_factory(), guarded by try/except (Req 8.5)
      3. message creation via message_factory() -> (subject, message)
      4. messaging.post_mattermost, guarded by try/except
      5. messaging.send_alert
      6. alarming.record_send
      7. os.remove(filename) if a file was produced
      8. messaging.icinga heartbeat

    Alarm-specific arguments are forwarded through can_send_kwargs and
    record_kwargs (e.g. Infrasound's volcano target name) (Req 8.6).

    Returns the final state_message (so the caller can use it if needed).
    """
    can_send_kwargs = can_send_kwargs or {}
    record_kwargs = record_kwargs or {}

    # 1. rate limit (Req 8.4)
    if not alarming.can_send(config, T0=T0, test=test_flag, **can_send_kwargs):
        logger.warning(f"Rate limit: skipping alarm {config.alarm_name}")
        state_message = f"{state_message} (alarm skipped due to rate limit)"
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return state_message

    # 2. figure (Req 8.5)
    try:
        filename = figure_factory()
    except Exception as e:
        logger.error("problem generating figure")
        logger.error(e)
        logger.error(traceback.format_exc())
        filename = None

    # 3. message
    subject, message = message_factory()

    # 4. mattermost (guarded)
    try:
        mm_url = messaging.post_mattermost(
            config, subject, message, attachment=filename, send=mm_flag, test=test_flag
        )
        message = f"{message}\n\n{mm_url}"
    except Exception as e:
        logger.error("problem posting to mattermost")
        logger.error(e)
        logger.error(traceback.format_exc())

    # 5. email/sms
    messaging.send_alert(
        config.alarm_name, subject, message, attachment=filename, test=test_flag
    )

    # 6. record send
    alarming.record_send(config, T0, test=test_flag, **record_kwargs)

    # 7. cleanup
    if filename:
        os.remove(filename)

    # 8. icinga heartbeat
    messaging.icinga(config, state, state_message, send=icinga_flag)
    return state_message
