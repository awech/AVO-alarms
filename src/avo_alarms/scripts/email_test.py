import os
import socket
from pathlib import Path

from obspy import UTCDateTime

from ..utils.messaging import send_alert
from ..utils.setup_utils import get_logger, setup_root_logger


def main():

    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Email_test")
    else:
        setup_root_logger()
    logger = get_logger(__name__)

    logger.info("Sending email test alert")

    T0 = UTCDateTime.now() - 3600 * 9
    hostname = socket.gethostname()
    message = f"{T0.strftime('%Y-%m-%d %H:%M')} from {hostname} user {os.environ.get('LOGNAME')}"
    subject = "Alarm Email Test"

    attachment = Path(os.environ["HOME_DIR"]) / "alarm_aux_files" / "oops.jpg"
    send_alert("Error", subject, message, attachment)
    logger.info("Finished")


if __name__ == "__main__":
    main()
