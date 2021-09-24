alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Okmok RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor. mmh

# SCNL=[
# {'scnl':'OKER.EHZ.AV.--'	, 'value': 400		},
# {'scnl':'OKNC.BHZ.AV.--'	, 'value': 400		},
# {'scnl':'OKTU.EHZ.AV.--'	, 'value': 400		},
# {'scnl':'OKWE.EHZ.AV.--'	, 'value': 400		},
# {'scnl':'MREP.EHZ.AV.--'	, 'value': 100		}, # arrestor station
# ]

SCNL=[
{'scnl':'OKCF.BHZ.AV.--'	, 'value': 675		},
{'scnl':'OKNO.BHZ.AV.--'	, 'value': 375		},
{'scnl':'OKBR.BHZ.AV.--'	, 'value': 1225		},
{'scnl':'OKFG.BHZ.AV.--'	, 'value': 300		},
{'scnl':'OKTU.BHZ.AV.--'	, 'value': 550		},
{'scnl':'OKNC.BHZ.AV.--'	, 'value': 775		},
{'scnl':'OKCE.BHZ.AV.--'	, 'value': 675		},
{'scnl':'MGOD.BHZ.AV.--'	, 'value': 100		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 4    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
