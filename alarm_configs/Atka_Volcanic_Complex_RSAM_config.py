alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Atka Volcanic Complex RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
#													  
SCNL=[
{'scnl':'KONW.BHZ.AV.--'	, 'value':  1100	},
{'scnl':'KOWE.BHZ.AV.--'	, 'value':   800	},
{'scnl':'KOKL.BHZ.AV.--'	, 'value':   700	},
{'scnl':'KOFP.BHZ.AV.--'	, 'value':   450	},
{'scnl':'KOSE.BHZ.AV.--'	, 'value':   600	},
{'scnl':'GSCK.BHZ.AV.--'	, 'value':   600 	}, # arrestor station 
# {'scnl':'GSIG.BHZ.AV.--'	, 'value':  150 	}, # arrestor station 
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

icinga_service_name = 'Korovin RSAM'
# mattermost_channel_id = 'jewennqiq7rd5kdubg8t1j9b8a'