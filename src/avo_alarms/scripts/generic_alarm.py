import sys

from ..utils.messaging import icinga


def config():
    return


def main():

    alarm_name = sys.argv[1].replace("_", " ")
    config.icinga_service_name = alarm_name
    config.alarm_name = alarm_name

    state = "OK"
    state_message = "Empty alarm service"

    icinga(config, state, state_message)


if __name__ == "__main__":
    main()
