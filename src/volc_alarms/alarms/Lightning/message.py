"""
Message construction for the Lightning alarm.

Formats the subject line and body text for a lightning-detection alert,
including new and total stroke counts, the most recent stroke time, its
distance and compass direction from the volcano, and the data source.
"""

from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import get_logger

from .detection import get_direction

logger = get_logger(__name__)


def create_message(df_new, df_recent):
    """Build the Lightning detection subject and message body.

    Parameters
    ----------
    df_new : pandas.DataFrame
        Newly detected strokes, with ``dataSource`` and location columns.
    df_recent : pandas.DataFrame
        All recent strokes for the volcano (new plus previously seen), with
        ``v_name``, ``v_distance``, ``time``, and location/API columns.

    Returns
    -------
    subject : str
        The alert subject line.
    message : str
        The formatted alert body.
    """

    v_last = df_recent.iloc[-1]
    v_name = v_last.v_name
    subject = f"--- {v_name} Lightning ---"

    if len(df_new) == 1:
        message = f"\n{len(df_new)} new stroke! ({len(df_recent)} total)"
    else:
        message = f"\n{len(df_new)} new strokes! ({len(df_recent)} total)"

    message = f"{message}\n\n-- Most recent --"
    t = utc(df_recent.iloc[0].time)
    message = f"{message}\n{messaging.format_timestring(t)}"

    dist = v_last.v_distance
    _, az1, _ = gps2dist_azimuth(v_last.api_vlat, v_last.api_vlon, v_last.latitude, v_last.longitude)
    direction = get_direction(az1)
    message = f"{message}\n{dist:.0f} km {direction} of {v_name},"
    network_txt = ", ".join(df_new.dataSource.unique()).replace("EN", "Earth Networks")
    message = f"{message}\n\nData source: {network_txt}"

    return subject, message
