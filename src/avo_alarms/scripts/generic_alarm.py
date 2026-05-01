import os
import sys

from avo_alarms.utils.messaging import icinga
from avo_alarms.utils.setup_utils import get_logger, setup_root_logger


def config():
    return


def main():

    alarm_name = sys.argv[1].replace("_", " ")
    config.icinga_service_name = alarm_name
    config.alarm_name = alarm_name

    # log info if run from cron
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name=alarm_name)
    else:
        setup_root_logger()

    logger = get_logger(__name__)
    logger.info(f"Setting {config.alarm_name} icinga status to OK and empty.")

    state = "OK"
    state_message = "Empty alarm service"

    icinga(config, state, state_message)


if __name__ == "__main__":
    main()
