alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Semisopochnoi RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
NSLC=[
{'nslc':'AV.CEAP..BHZ'	, 'value':     650	},
{'nslc':'AV.CERA..BHZ'	, 'value':     750	},
{'nslc':'AV.CETU..BHZ'	, 'value':     650	},
# {'nslc':'AV.CEPE..BHZ'  , 'value':     750  },
# {'nslc':'AV.CERB..BHZ'	, 'value':     1450	},
{'nslc':'AV.CERB..BDF'	, 'value':     1e7  }, # infrasound channel (for plotting only)
{'nslc':'AV.CESW..BDF'	, 'value':     1e7  }, # infrasound channel (for plotting only)
{'nslc':'AV.CESW..BHZ'	, 'value':     900	},
{'nslc':'AV.AMKA..BHZ'	, 'value':     350	}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

VOLCANO_NAME = 'Semisopochnoi'
