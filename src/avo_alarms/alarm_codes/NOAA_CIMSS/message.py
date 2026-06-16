from obspy import UTCDateTime as utc

from avo_alarms.utils import messaging
from avo_alarms.utils.messaging import post_mattermost
from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def create_message(alert, volcs, output_text):

    t = utc(alert.object_date_time)
    instrument = output_text["instrument"]
    height_txt = output_text["height_txt"]
    status_txt = output_text["status_txt"]
    type_txt = output_text["type_txt"]
    message = messaging.format_timestring(t)


    message += f"\n**Primary Instrument:** {instrument}"
    if height_txt:
        height_txt = height_txt.replace("Max", "**Max").replace("]:", "]:**")
        message += f"\n{height_txt}"
    if status_txt:
        status_txt = status_txt.replace("Alert", "**Alert").replace(":", ":**")
        message += f"\n{status_txt}"
    if type_txt:
        type_txt = type_txt.replace("Type of Volcanic Event:", "**Event type:**")
        message += f"\n{type_txt}"
    message += f"\n**Latitude:** {alert.lat_rc:.3f}\n**Longitude:** {alert.lon_rc:.3f}\n"

    v_text = ""
    for i, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Name} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")

    message += f"**Method:** {alert.method}\n"
    message += f"**Nearest volcanoes:** {v_text[:-2]}\n\n"
    message += f"**More info:** {alert.alert_url.replace('report/' + str(alert.NOAA_id), 'individual/' + str(alert.aid))}\n"

    subject_text = alert.alert_header.title().replace(" Found", "")
    subject_text = subject_text.replace(" Detected", "")
    subject = f"{volcs.iloc[0].Name}: {subject_text}"

    return subject, message


def cimss_mm_channels(alert, config, subject, message, attachment, test_flag, mm_flag):
    
    ##################################################################
    # Send thermal alerts to their own channel
    if (alert.alert_type == "hot") and ("THERMAL" in alert.alert_header):
        if alert.v_distance < getattr(config, "thermal_alert_dist", 20):
            config.mattermost_channel_id = config.thermal_alerts_mm
            post_mattermost(config, subject, message, attachment=attachment, send=mm_flag, test=test_flag)
    ##################################################################

    ##################################################################
    # Send alerts for elevated volcanoes to their own channel
    if (alert.v_distance < config.elevated_volcano_dist) and (alert.v_name in config.elevated_volcano_list):
        config.mattermost_channel_id = config.elevated_volcano_mm
        post_mattermost(config, subject, message, attachment=attachment, send=mm_flag, test=test_flag)
    ##################################################################

    return
