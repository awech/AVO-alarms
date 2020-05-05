alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Veniaminof RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL=[
# {'scnl':'VNSS.EHZ.AV.--'	, 'value': 800		},
{'scnl':'VNSS.EHZ.AV.--'	, 'value': 1150		}, # changed 29-Oct-2018 to avoid network-wide noise spikes
{'scnl':'VNFG.EHZ.AV.--'	, 'value': 150		},
# {'scnl':'VNHG.EHZ.AV.--'	, 'value': 600		},
{'scnl':'VNHG.EHZ.AV.--'	, 'value': 750		}, # changed 29-Oct-2018 to avoid network-wide noise spikes
{'scnl':'VNWF.EHZ.AV.--'	, 'value': 500		},
# {'scnl':'CHGN.BHZ.AT.--'	, 'value': 80		}, # arrestor station
{'scnl':'SDPT.BHZ.AT.--'	, 'value': 200	}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 4    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
