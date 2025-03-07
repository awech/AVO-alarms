import sys
from pathlib import Path

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils.messaging import icinga


def config():
    return


def send_empty_icinga():

    alarm_name = sys.argv[1].replace("_", " ")
    config.icinga_service_name = alarm_name
    config.alarm_name = alarm_name

    state = "OK"
    state_message = "Empty alarm service"

    icinga(config, state, state_message)


if __name__ == "__main__":
    send_empty_icinga()
