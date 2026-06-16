from obspy import UTCDateTime as utc
from obspy.geodetics.base import gps2dist_azimuth

from avo_alarms.utils import messaging
from avo_alarms.utils.setup_utils import get_logger

from .detection import get_direction

logger = get_logger(__name__)


def create_message(df_new, df_recent):

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
