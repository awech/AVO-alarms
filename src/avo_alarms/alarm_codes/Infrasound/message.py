import numpy as np
from obspy import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth

from avo_alarms.utils import messaging


def create_message(t1, t2, st, target, azimuth, d_Azimuth, velocity, mx_pressure):
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
