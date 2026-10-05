"""
Message construction for the VAA alarm.

Formats the subject line and Markdown body for a Volcanic Ash Advisory alert,
leading with the observed ash-cloud flight levels and advisory time, then
reproducing the original advisory fields.
"""

from obspy import UTCDateTime

from volc_alarms.utils import messaging
from volc_alarms.utils.setup_utils import get_logger

from .detection import process_polygons

logger = get_logger(__name__)


def create_message(vaa):
    """Build the VAA alert subject and message body.

    Parameters
    ----------
    vaa : dict
        Parsed advisory record, as produced by
        :func:`.detection.process_vaa_id` (exposes ``VOLCANO``, ``time``, the
        advisory text fields, and ``OBS VA CLD``).

    Returns
    -------
    subject : str
        Subject line naming the volcano.
    message : str
        Markdown body with the observed flight levels, advisory time, and the
        reproduced advisory fields.
    """

    volcano_name = "".join(vaa["VOLCANO"].split(" ")[:-1]).title()
    subject = f'{volcano_name} Volcanic Ash Advisory'

    t = UTCDateTime(vaa["time"])
    time_txt = messaging.format_timestring(t)

    try:
        groups_0 = process_polygons(vaa, "OBS VA CLD")
        levels = ", ".join(dict.fromkeys(lt for _, _, lt in groups_0 if lt))
        message = f"VAA {levels}\n{time_txt}\n\n#### *Original Message*\n"
    except Exception as e: # noqa: BLE001
        logger.warning("Error generating message contents")
        logger.error(e)
        message = f"Volcanic Ash Advisory\n{time_txt}\n\n#### *Original Message*\n"
    
    for key in vaa.keys():  # noqa: SIM118
        if key not in ["header", "id", "time", "v_name"]:
            if isinstance(vaa[key], str):
                key_str = vaa[key].replace('\n', ' ')
                message += f"**{key}:** {key_str}\n"

    message = message.replace("\r\n", " ")

    return subject, message
