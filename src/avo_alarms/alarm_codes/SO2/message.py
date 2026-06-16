import os

from obspy import UTCDateTime

from avo_alarms.utils import messaging


def create_message(date, time, table, config, volcs):

    subject = "SO2 detection"

    message = f"{messaging.format_timestring(UTCDateTime(time))}"

    message += "\n".join(table[2:])
    # message = message.replace('     ',' ')
    # message = message.replace('   ',' ')
    # message = message.replace('  ',' ')
    message = message.replace(" deg.", "")

    v_text = ""
    for i, row in volcs.sort_values("distance")[:3].iterrows():
        v_text = f"{v_text}{row.Name} ({row.distance:.0f} km), "
    v_text = v_text.replace("_", " ")
    message = f"{message}\n\nNearest volcanoes: {v_text[:-2]}\n"
    message += f"\n{os.environ['SACS_URL']}"

    return subject, message
