"""
Message construction for the Pilot Report (PIREP) alarm.

Formats the subject line and body text for a PIREP alert, including the report
time, flight level, pilot remark, location, nearest volcanoes, and the
original report text. Urgent reports get an ``URGENT!`` subject prefix.
"""

from obspy import UTCDateTime as utc

from volc_alarms.utils import messaging, processing
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import get_height_text, get_pilot_remark

logger = get_logger(__name__)


def create_message(pirep_row, config):
    """Build the PIREP alert subject and message body.

    Parameters
    ----------
    pirep_row : pandas.Series
        A single PIREP report row exposing ``time``, ``FL``, ``REPORT``,
        ``lat``, ``lon``, and ``URGENT``.
    config : object
        PIREP alarm configuration (currently unused, kept for signature
        consistency).

    Returns
    -------
    subject : str
        Subject line naming the nearest volcanoes (prefixed ``URGENT!`` for
        urgent reports).
    message : str
        Message body with time, flight level, pilot remark, location, nearest
        volcanoes, and the original report.
    """
    message = messaging.format_timestring(utc(pirep_row.time))
    message += f"\n{get_height_text(pirep_row.FL)}\nPilot Remark: {get_pilot_remark(pirep_row.REPORT)}"
    message += f"\nLatitude: {pirep_row.lat:.3f}\nLongitude: {pirep_row.lon:.3f}\n"

    volcs = load_volcano_list()
    volcs = processing.volcano_distance(pirep_row.lon, pirep_row.lat, volcs, filter_col="PIREP")

    v_text = messaging.format_nearest_volcanoes(volcs)
    message = f"{message}Nearest volcanoes: {v_text}\n"
    message = f"{message}\n--Original Report--\n{pirep_row.REPORT}"
    logger.info(message)

    if pirep_row.URGENT == "T":
        subject = f"URGENT! Activity possible at: {v_text}"
    else:
        subject = f"Activity possible at: {v_text}"

    return subject, message
