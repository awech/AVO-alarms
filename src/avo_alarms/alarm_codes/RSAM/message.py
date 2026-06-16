import numpy as np

from avo_alarms.utils import messaging


def create_message(t1, t2, stations, rms, lvlv, DR, alarm_name):
    """Build the RSAM alert subject and message body.

    Parameters
    ----------
    t1 : obspy.UTCDateTime
        Start time of the detection window.
    t2 : obspy.UTCDateTime
        End time of the detection window.
    stations : list
        List of station names.
    rms : numpy.ndarray
        RMS values for each station.
    lvlv : numpy.ndarray
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

    a = np.array([""] * len(rms[:-1]))
    a[np.where(rms > lvlv)] = "*"

    if any(DR):
        sta_message = "".join(
            f"{sta}{a[i]}: {rms[i]:.0f}/{lvlv[i]:.0f} (RD = {DR[i]:.1f})\n"
            for i, sta in enumerate(stations[:-1])
        )
    else:
        sta_message = "".join(
            f"{sta}{a[i]}: {rms[i]:.0f}/{lvlv[i]:.0f}\n"
            for i, sta in enumerate(stations[:-1])
        )
    sta_message = "".join(
        [sta_message, f"\nArrestor: {stations[-1]} {rms[-1]:.0f}/{lvlv[-1]:.0f}"]
    )
    message = "".join([message, sta_message])

    return subject, message
