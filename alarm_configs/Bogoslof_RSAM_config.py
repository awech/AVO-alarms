alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Bogoslof RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
# SCNL=[
# {'scnl':'OKFG.BHN.AV.--'	, 'value': 10000	},
# {'scnl':'MAPS.BHZ.AV.--'	, 'value': 150		},
# {'scnl':'MSW.BHN.AV.--'		, 'value': 75		},
# {'scnl':'MGOD.BHN.AV.--'	, 'value': 150		},
# {'scnl':'AKMO.BHN.AV.--'	, 'value': 1000		},
# {'scnl':'NIKH.BHZ.AK.--'	, 'value': 150		}, # arrestor station
# ]

# SCNL=[
# {'scnl':'OKER.EHZ.AV.--'	, 'value': 150		},
# {'scnl':'OKTU.EHZ.AV.--'	, 'value': 150		},
# {'scnl':'MAPS.BHZ.AV.--'	, 'value': 150		},
# {'scnl':'MREP.EHZ.AV.--'	, 'value': 50		},
# {'scnl':'MSW.BHN.AV.--'		, 'value': 75		},
# {'scnl':'MGOD.BHN.AV.--'	, 'value': 150		},
# {'scnl':'NIKH.BHZ.AK.--'	, 'value': 150		}, # arrestor station
# ]

SCNL=[
{'scnl':'OKER.EHZ.AV.--'	, 'value': 300		},
{'scnl':'OKTU.EHZ.AV.--'	, 'value': 250		},
{'scnl':'MAPS.BHZ.AV.--'	, 'value': 300		},
{'scnl':'MREP.EHZ.AV.--'	, 'value': 100		},
{'scnl':'MSW.BHN.AV.--'		, 'value': 150		},
{'scnl':'MGOD.BHN.AV.--'	, 'value': 300		},
{'scnl':'NIKH.BHZ.AK.--'	, 'value': 150		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 4    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.5  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter