from obspy import UTCDateTime as utc

from volc_alarms.utils import messaging, processing
from volc_alarms.utils.setup_utils import get_logger, load_volcano_list

from .detection import get_height_text, get_pilot_remark

logger = get_logger(__name__)


def create_message(pirep_row, config):

    message = messaging.format_timestring(utc(pirep_row.time))
    message += f"\n{get_height_text(pirep_row.FL)}\nPilot Remark: {get_pilot_remark(pirep_row.REPORT)}"
    message += f"\nLatitude: {pirep_row.lat:.3f}\nLongitude: {pirep_row.lon:.3f}\n"

    volcs = load_volcano_list()
    volcs = processing.volcano_distance(pirep_row.lon, pirep_row.lat, volcs)

    v_text = ""
    for j, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Name} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}Nearest volcanoes: {v_text[:-2]}\n"
    message = f"{message}\n--Original Report--\n{pirep_row.REPORT}"
    logger.info(message)

    if pirep_row.URGENT == "T":
        subject = f"URGENT! Activity possible at: {v_text[:-2]}"
    else:
        subject = f"Activity possible at: {v_text[:-2]}"

    return subject, message
