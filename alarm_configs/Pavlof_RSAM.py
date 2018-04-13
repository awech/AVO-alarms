alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Pavlof RSAM'		# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL=[
{'scnl':'PS4A.BHZ.AV.--'	, 'value': 200	},
# {'scnl':'PS4A.EHZ.AV.--'	, 'value': 600	},
{'scnl': 'PVV.SHZ.AV.--'	, 'value': 200	},
{'scnl':'PS1A.BHZ.AV.--'	, 'value': 200	},
{'scnl': 'HAG.SHZ.AV.--'	, 'value': 200	},
# {'scnl': 'HAG.EHZ.AV.--'	, 'value': 2500	},
{'scnl':'PN7A.BHZ.AV.--'	, 'value': 220	},
{'scnl':'PV6A.SHZ.AV.--'	, 'value': 200	},
{'scnl':'SDPT.BHZ.AT.--'	, 'value': 400	}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
