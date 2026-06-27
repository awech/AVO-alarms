from obspy import UTCDateTime as utc

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import get_logger

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


def cimss_extra_channels(alert, config):
    """Return the list of additional Mattermost channel ids for an alert.

    Routing decisions (thermal alerts, elevated-volcano alerts) live here in the
    alarm; the actual posting is handled by ``post_mattermost(channel_ids=...)``.
    """
    channels = []

    # Thermal alerts get their own channel.
    if (alert.alert_type == "hot") and ("THERMAL" in alert.alert_header):
        if alert.v_distance < getattr(config, "thermal_alert_dist", 20):
            channels.append(config.thermal_alerts_mm)

    # Alerts for elevated volcanoes get their own channel.
    if (alert.v_distance < config.elevated_volcano_dist) and (alert.v_name in config.elevated_volcano_list):
        channels.append(config.elevated_volcano_mm)

    return channels
