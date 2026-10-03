"""
Message construction and channel routing for the NOAA/CIMSS alarm.

Formats the subject line and body text for a satellite-alert notification
(instrument, height, status, event type, location, method, and nearest
volcanoes), and determines any extra Mattermost channels an alert should also
be posted to.
"""

from obspy import UTCDateTime as utc

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def create_message(alert, volcs, output_text):
    """Build the NOAA/CIMSS alert subject and message body.

    Parameters
    ----------
    alert : pandas.Series
        Alert row exposing ``object_date_time``, ``alert_header``,
        ``lat_rc``/``lon_rc``, ``method``, ``alert_url``, ``NOAA_id``, and
        ``aid``.
    volcs : pandas.DataFrame
        Volcano table with a ``distance`` column, used for the nearest-volcano
        summary and to pick the subject's volcano.
    output_text : dict
        Scraped detail fields: ``instrument``, ``height_txt``, ``status_txt``,
        and ``type_txt``.

    Returns
    -------
    subject : str
        The alert subject line.
    message : str
        The formatted alert body (Mattermost markdown).
    """
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

    v_text = messaging.format_nearest_volcanoes(volcs)

    message += f"**Method:** {alert.method}\n"
    message += f"**Nearest volcanoes:** {v_text}\n\n"
    message += f"**More info:** {alert.alert_url.replace('report/' + str(alert.NOAA_id), 'individual/' + str(alert.aid))}\n"

    subject_text = alert.alert_header.title().replace(" Found", "")
    subject_text = subject_text.replace(" Detected", "")
    nearest_volcano = volcs.loc[volcs["distance"].idxmin()].Name
    subject = f"{nearest_volcano}: {subject_text}"

    return subject, message


def cimss_extra_channels(alert, config):
    """Return the list of additional Mattermost channel ids for an alert.

    Routing decisions (thermal alerts, elevated-volcano alerts) live here in
    the alarm; the actual posting is handled by
    ``post_mattermost(channel_ids=...)``.

    Parameters
    ----------
    alert : pandas.Series
        Alert row exposing ``alert_type``, ``alert_header``, ``v_distance``,
        and ``v_name``.
    config : object
        Configuration exposing the channel ids and distance thresholds
        (``thermal_alert_dist``, ``thermal_alerts_mm``,
        ``elevated_volcano_dist``, ``elevated_volcano_list``,
        ``elevated_volcano_mm``).

    Returns
    -------
    list of str
        Extra Mattermost channel ids to also post to (possibly empty).
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
