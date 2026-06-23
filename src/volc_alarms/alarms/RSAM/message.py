import numpy as np

from volc_alarms.utils import messaging


def create_message(t1, t2, stations, rsam, levels, DR, alarm_name):
    """Build the RSAM alert subject and message body.

    Parameters
    ----------
    t1 : obspy.UTCDateTime
        Start time of the detection window.
    t2 : obspy.UTCDateTime
        End time of the detection window.
    stations : list
        List of station names.
    rsam : numpy.ndarray
        rsam values for each station.
    levels : numpy.ndarray
        Threshold values for each station.
    DR : list or numpy.ndarray
        Reduced displacement values (may be empty).
    alarm_name : str
        Name of the alarm for the subject line.

    Returns
    -------
    tuple
        (subject, message) strings.
    """

    # create the subject line
    subject = f"--- {alarm_name} ---"

    # create the text for the message you want to send
    message = f"{messaging.format_timestring(t1, t2)}\n\n"

    a = np.array([""] * len(rsam[:-1]))
    a[np.where(rsam > levels)] = "*"

    if any(DR):
        sta_message = "".join(
            f"{sta}{a[i]}: {rsam[i]:.0f}/{levels[i]:.0f} (RD = {DR[i]:.1f})\n"
            for i, sta in enumerate(stations[:-1])
        )
    else:
        sta_message = "".join(
            f"{sta}{a[i]}: {rsam[i]:.0f}/{levels[i]:.0f}\n"
            for i, sta in enumerate(stations[:-1])
        )
    sta_message = "".join(
        [sta_message, f"\nArrestor: {stations[-1]} {rsam[-1]:.0f}/{levels[-1]:.0f}"]
    )
    message = "".join([message, sta_message])

    return subject, message
