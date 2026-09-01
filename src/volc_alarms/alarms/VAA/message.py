from obspy import UTCDateTime

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import get_logger

from .detection import process_polygons

logger = get_logger(__name__)


def create_message(vaa):

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    subject = f'{volcano_name} Volcanic Ash Advisory'

    t = UTCDateTime(vaa["time"])
    time_txt = messaging.format_timestring(t)

    try:
        lons_0, lats_0, level_0 = process_polygons(vaa, "OBS VA CLD")
        message = f"VAA {level_0}\n{time_txt}\n\n#### *Original Message*\n"
    except Exception as e:
        logger.warning("Error generating message contents")
        logger.error(e)
        message = f"Volcanic Ash Advisory\n{time_txt}\n\n#### *Original Message*\n"
    
    for key in vaa.keys():
        if key not in ["header", "id", "time", "v_name"]:
            if isinstance(vaa[key], str):
                key_str = vaa[key].replace('\n', ' ')
                message += f"**{key}:** {key_str}\n"

    message = message.replace("\r\n", " ")

    return subject, message
