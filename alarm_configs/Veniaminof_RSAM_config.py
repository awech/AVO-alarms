alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Veniaminof RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL=[
{'scnl':'VNCG.BHZ.AV.--'	, 'value': 3000		}, # changed 29-Oct-2018 to avoid network-wide noise spikes
{'scnl':'VNSW.BHZ.AV.--'	, 'value': 3000		},
{'scnl':'VNWF.BHZ.AV.--'	, 'value': 3000		},
{'scnl':'VNKR.BHZ.AV.--'	, 'value': 3000		},
{'scnl':'VNSO.BHZ.AV.--'	, 'value': 3000		},
{'scnl':'VNSG.BHZ.AV.--'	, 'value': 3000		},
{'scnl':'SDPT.BHZ.AT.--'	, 'value': 200	}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 7    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
