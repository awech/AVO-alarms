import traceback

from avo_alarms.utils import processing, downloading
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

from .figure import plot_event
from .message import create_message

logger = get_logger(__name__)


def process_event(evt_url, config, test=False):

    cat = downloading.download_hypocenter_xml(evt_url)
    try:
        cat = processing.addPhaseHint(cat)
    except Exception as e:
        logger.warning('Could not add phase type...')
        logger.error(e)

    # Find nearby volcanoes
    eq = cat[0]
    origin = eq.preferred_origin()
    volcs = load_volcano_list()
    volcs = processing.volcano_distance(origin.longitude, origin.latitude, volcs)

    try:
        filename = plot_event(eq, volcs, config, test=test)
        eq_time = origin.time.strftime("%Y%m%dT%H%M%S")
        eq_mag = eq.preferred_magnitude().mag
        eq_id = "".join(eq.resource_id.id.split("/")[-2:]).lower()
        new_filename = f"{eq_time}_M{eq_mag:.1f}_{eq_id}{filename.suffix}"
        filename = filename.rename(filename.parent / new_filename)
    except Exception as e:
        filename = []
        logger.error("Problem making figure. Continue anyway")
        logger.error(e)
        logger.error(traceback.format_exc())

    subject, message = create_message(eq, volcs)

    return subject, message, filename, eq, volcs
