alarm_type = "RSAM"  # this designates which alarm module will be imported and executed
alarm_name = (
    "Pavlof RSAM"  # this is the alarm name sent to icinga and in message alerts
)

# Stations list. Last station is arrestor.
SCNL = [
    {"scnl": "PS4A.BHZ.AV.--", "value": 400},
    {"scnl": "PVV.BHZ.AV.--", "value": 400},
    {"scnl": "PS1A.BHZ.AV.--", "value": 375},
    {"scnl": "HAG.BHZ.AV.--", "value": 300},
    {"scnl": "PN7A.BHZ.AV.--", "value": 450},
    {"scnl": "PV6A.BHZ.AV.--", "value": 325},
    # {'scnl':'FALS.BHZ.AK.--'	, 'value': 200	}, # arrestor station, out since May 23, 2019
    {"scnl": "BLDW.BHZ.AV.--", "value": 200},  # arrestor station
]

duration = 5 * 60  # duration value in seconds
latency = 10  # seconds between timestamps and end of data window
min_sta = 3  # minimum number of stations for detection
taper_val = 5  # seconds to taper beginning and end of trace before filtering
f1 = 1.0  # minimum frequency for bandpass filter
f2 = 5.0  # maximum frequency for bandpass filter

plot_duration = 3600

VOLCANO_NAME = "Pavlof"
