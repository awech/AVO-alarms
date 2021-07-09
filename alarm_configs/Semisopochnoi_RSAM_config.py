alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Semisopochnoi RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL=[
{'scnl':'CEAP.BHZ.AV.--'	, 'value':     475		},
# {'scnl':'CEPE.SHZ.AV.--'	, 'value':  500 * 1e3		}, # removed Feb 28, 2020. Dead channel.
{'scnl':'CEPE.BHZ.AV.--'	, 'value':     600		},
{'scnl':'CESW.BHZ.AV.--'	, 'value':     700		},
{'scnl':'CETU.BHZ.AV.--'	, 'value':     475		},
{'scnl':'AMKA.BHZ.AV.--'	, 'value':     100		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter
