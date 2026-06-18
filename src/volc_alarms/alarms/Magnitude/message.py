import os
import traceback

import pandas as pd

from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def create_message(eq, volcs):
    origin = eq.preferred_origin()
    t = pd.Timestamp(origin.time.datetime, tz="UTC")
    t_local = t.tz_convert(os.getenv("TIMEZONE"))
    Local_time_text = f"{t_local.strftime('%Y-%m-%d %H:%M:%S')} {t_local.tzname()}"

    message = f"{t.strftime('%Y-%m-%d %H:%M:%S')} UTC\n{Local_time_text}"
    message = f"{message}\n\n**Magnitude:** {eq.preferred_magnitude().mag:.1f}"
    message = f"{message}\n**Latitude:** {origin.latitude:.3f}\n**Longitude:** {origin.longitude:.3f}"
    message = f"{message}\n**Depth:** {origin.depth / 1000:.1f} km"
    message = f"{message}\n**Event ID:** {''.join(eq.resource_id.id.split('/')[-2:]).lower()}"

    volcs = volcs.sort_values("distance")
    v_text = ""
    for _, row in volcs[:3].iterrows():
        v_text = f"{v_text}{row.Name} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}\n**Nearest volcanoes:** {v_text[:-2]}"

    try:
        message = f"{message}\n\n***--- {origin.evaluation_mode.replace('manual', 'reviewed').upper()} Location ---***"
        message = f"{message}\nUsing {origin.quality.used_phase_count:g} phases from {origin.quality.used_station_count:g} stations"
        message = f"{message}\n**Azimuthal Gap:** {origin.quality.azimuthal_gap:g} degrees"
        message = f"{message}\n**Standard Error:** {origin.quality.standard_error:g} s"
        message = f"{message}\n**Vertical/Horizontal Error:** {origin.depth_errors['uncertainty'] / 1000:.1f} km / {origin.origin_uncertainty.horizontal_uncertainty / 1000:.1f} km"
    except Exception as e:
        logger.warning("Problem adding location quality info to message. Continue anyway.")
        logger.warning(e)
        logger.warning(traceback.format_exc())
        pass

    subject = f"M{eq.preferred_magnitude().mag:.1f} earthquake at {volcs.iloc[0].Name}"

    return subject, message
