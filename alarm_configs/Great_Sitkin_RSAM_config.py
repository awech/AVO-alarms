alarm_type = "RSAM"  # this designates which alarm module will be imported and executed
alarm_name = "Great Sitkin RSAM"  # this is the alarm name sent to icinga and in message alerts


# Stations list. Last station is arrestor.
SCNL = [
    {"scnl": "GSTD.BHZ.AV.--", "value": 1125},
    {"scnl": "GSTR.BHZ.AV.--", "value": 1000},
    {"scnl": "GSMY.BHZ.AV.--", "value": 850 },
    {"scnl": "GSSP.BHZ.AV.--", "value": 875 },
    {"scnl": "GSCK.BHZ.AV.--", "value": 675 },
    # {'scnl':'ADAG.BHZ.AV.--'	, 'value':  3 * 175 }, # arrestor station
    {"scnl": "KIRH.BHZ.AV.--", "value": 3 * 60},  # arrestor station
    # {'scnl':'KIMD.BHZ.AV.--'	, 'value':  50      }, # arrestor station
]

duration  = 5 * 60 # duration value in seconds
latency   = 10     # seconds between timestamps and end of data window
min_sta   = 3      # minimum number of stations for detection
taper_val = 5      # seconds to taper beginning and end of trace before filtering
f1        = 1.0    # minimum frequency for bandpass filter
f2        = 5.0    # maximum frequency for bandpass filter

VOLCANO_NAME = "Great Sitkin"