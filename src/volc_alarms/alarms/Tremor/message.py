"""
Message construction for the Tremor alarm.

Formats the subject line and body text for a tremor/swarm detection alert from
the alarm name, time window, and a seismicity-summary statement.
"""

from volc_alarms.utils import messaging


def create_message(t1, t2, alarm_name, statement):
    """Build the Tremor alert subject and message body.

    Parameters
    ----------
    t1 : obspy.UTCDateTime
        Start time of the lookback window.
    t2 : obspy.UTCDateTime
        End time of the lookback window.
    alarm_name : str
        Name of the alarm for the subject line.
    statement : str
        Seismicity-summary text to include in the body.

    Returns
    -------
    subject : str
        Subject line for the alert.
    message : str
        Message body with the formatted time window and statement.
    """

    subject = f"--- {alarm_name} ---"

    time_str = messaging.format_timestring(t1, t2)
    message = f"{time_str}\n\n{statement}"

    return subject, message
