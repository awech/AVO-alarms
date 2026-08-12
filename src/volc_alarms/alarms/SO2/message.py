import os

from obspy import UTCDateTime

from volc_alarms.utils import messaging


def create_message(date, time, table, config, volcs):

    subject = "SO2 detection"

    message = f"{messaging.format_timestring(UTCDateTime(time))}"

    message += "\n".join(table[2:])
    # message = message.replace('     ',' ')
    # message = message.replace('   ',' ')
    # message = message.replace('  ',' ')
    message = message.replace(" deg.", "")

    v_text = messaging.format_nearest_volcanoes(volcs)
    message = f"{message}\n\nNearest volcanoes: {v_text}\n"
    message += f"\n{os.environ['SACS_URL']}"

    return subject, message
