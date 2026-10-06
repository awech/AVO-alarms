"""
Message construction for the Infrasound alarm.

Formats the subject line and body text for an airwave-detection alert,
including azimuth, back-azimuth deviation, trace velocity, peak pressure, and
(when target coordinates are available) an estimated acoustic travel time.
"""

import numpy as np
from obspy import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth

from volc_alarms.utils import messaging


def create_message(t1, t2, st, target, azimuth, d_Azimuth, velocity, mx_pressure):
    """Build the Infrasound airwave-detection subject and message body.

    Parameters
    ----------
    t1 : obspy.UTCDateTime
        Start time of the detection window.
    t2 : obspy.UTCDateTime
        End time of the detection window.
    st : obspy.Stream
        Stream whose traces carry ``stats.coordinates``, used to estimate the
        array center for the travel-time calculation.
    target : dict
        Target definition, including ``name``, ``lat``/``lon``, and optionally
        ``traveltime`` (set False to suppress the travel-time line).
    azimuth : float
        Mean observed back-azimuth, in degrees.
    d_Azimuth : float
        Deviation of the observed azimuth from the target back-azimuth, in
        degrees.
    velocity : float
        Mean trace velocity, in km/s (printed as m/s).
    mx_pressure : float
        Peak detected pressure, in Pa.

    Returns
    -------
    subject : str
        The alert subject line.
    message : str
        The formatted alert body.
    """

    # create the subject line
    subject = f"{target['name']} Airwave Detection"

    # create the text for the message you want to send
    message = f"{messaging.format_timestring(t1, t2)}\n\n"

    message = f"{message}Azimuth: {azimuth:+.1f} degrees\n"
    message = f"{message}d_Azimuth: {d_Azimuth:+.1f} degrees\n"
    message = f"{message}Velocity: {velocity * 1000:.0f} m/s\n"
    message = f"{message}Max Pressure: {mx_pressure:.1f} Pa"

    calc_tt = True
    if "traveltime" in target:
        calc_tt = target["traveltime"]
    if ("lat" in target) & calc_tt:
        lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
        lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
        travel_time = UTCDateTime(
            gps2dist_azimuth(lat0, lon0, target["lat"], target["lon"])[0] / 333
        )
        if travel_time.hour > 0:
            message = f"{message}\nTravel Time: {travel_time.hour:.0f}h {travel_time.minute:.0f}m {travel_time.second:.0f}s"
        else:
            message = f"{message}\nTravel Time: {travel_time.minute:.0f}m {travel_time.second:.0f}s"

    return subject, message
