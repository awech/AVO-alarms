from avo_alarms.utils import messaging


def create_message(t1, t2, alarm_name, statement):

    subject = f"--- {alarm_name} ---"

    time_str = messaging.format_timestring(t1, t2)
    message = f"{time_str}\n\n{statement}"

    return subject, message
