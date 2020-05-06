alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Okmok RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor. mmh

SCNL=[
{'scnl':'OKER.EHZ.AV.--'	, 'value': 400		},
{'scnl':'OKNC.BHZ.AV.--'	, 'value': 400		},
{'scnl':'OKTU.EHZ.AV.--'	, 'value': 400		},
{'scnl':'OKWE.EHZ.AV.--'	, 'value': 400		},
{'scnl':'MREP.EHZ.AV.--'	, 'value': 100		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
