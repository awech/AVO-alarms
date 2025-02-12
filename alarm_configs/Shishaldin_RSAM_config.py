alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Shishaldin RSAM'	# this is the alarm name sent to icinga and in message alerts

# # Stations list. Last station is arrestor.
# SCNL=[
# {'scnl':'SSLN.BHZ.AV.--'	, 'value': 4000		},
# {'scnl':'SSLS.BHZ.AV.--'	, 'value': 20000	},
# {'scnl':'SSBA.BHZ.AV.--'	, 'value': 700		},
# {'scnl':'ISNN.SHZ.AV.--'	, 'value': 1100		},
# {'scnl':'DTN.BHZ.AV.--'	, 'value': 250		}, # arrestor station
# ]

# Stations list. Last station is arrestor.
SCNL=[
{'scnl':'ISLZ.BHZ.AV.--'	, 'value': 1 * 350		},
{'scnl':'SSLS.BHZ.AV.--'	, 'value': 1 * 800		},
{'scnl':'SSLN.BHZ.AV.--'	, 'value': 1 * 1100	*2	}, # adjusted 2024-04-15 to temporarily supress wind noise
{'scnl':'SSBA.BHZ.AV.--'	, 'value': 1 * 600		},
{'scnl':'ISNN.BHZ.AV.--'	, 'value': 1 * 290		},
{'scnl':'BLDW.BHZ.AV.--'	, 'value': 250		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection							# adjusted 2->3 2024-04-15 to temporarily supress wind noise
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

VOLCANO_NAME = 'Shishaldin'