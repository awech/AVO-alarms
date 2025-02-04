alarm_type = "RSAM"  # this designates which alarm module will be imported and executed
alarm_name = "Spurr RSAM"  # this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL = [
    {"scnl": "SPBG.BHZ.AV.--", "value": 675},
    {"scnl": "SPCP.BHZ.AV.--", "value": 750},
    {"scnl": "SPCN.BHZ.AV.--", "value": 600},
    {"scnl": "N20K.BHZ.AV.--", "value": 850},
    {"scnl": "SPCL.BHZ.AV.--", "value": 475},
    {"scnl": "SPU.BHZ.AV.--", "value": 375},
    {"scnl": "SKN.BHZ.AK.--", "value": 75 * 3},  # arrestor station
]

duration = 5 * 60  # duration value in seconds
latency = 10  # seconds between timestamps and end of data window
min_sta = 3  # minimum number of stations for detection
taper_val = 5  # seconds to taper beginning and end of trace before filtering
f1 = 1.0  # minimum frequency for bandpass filter
f2 = 5.0  # maximum frequency for bandpass filter

plot_duration = 3600

VOLCANO_NAME = "Spurr"

icinga_service_name = "generic alarm 4"
mattermost_channel_id = "jewennqiq7rd5kdubg8t1j9b8a"
