alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'Saipan Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
	{'scnl':'FLX.HDF.MI.01'	, 'sta_lat': 15.23388	, 'sta_lon': 145.79172},
	{'scnl':'FLX.HDF.MI.02'	, 'sta_lat': 15.23320	, 'sta_lon': 145.79234},
	{'scnl':'FLX.HDF.MI.03'	, 'sta_lat': 15.23475	, 'sta_lon': 145.79216},
	# {'scnl':'FLX.HDF.MI.04'	, 'sta_lat': 15.23206	, 'sta_lon': 145.79389},
	{'scnl':'FLX.HDF.MI.05'	, 'sta_lat': 15.23215	, 'sta_lon': 145.79112},
	{'scnl':'FLX.HDF.MI.06'	, 'sta_lat': 15.23647	, 'sta_lon': 145.79045},
]


# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'North (Anatahan?)',	'v_lat': 18.141555,	'v_lon': 145.786260, 	
 			'Azimuth_tolerance': 15, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
			'seismic_scnl': ['FLX.BHZ.MI.--','DPS.BHZ.MI.--'], 'traveltime':False},
{'volcano':	'North (Pagan?)', 		'v_lat': 18.141555, 'v_lon': 145.786260,
 			'Azimuth_tolerance': 15, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
			'seismic_scnl': ['FLX.BHZ.MI.--','DPS.BHZ.MI.--'], 'traveltime':False},
]

duration  = 3*60 # duration value in seconds
latency   = 180.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/400000)/0.0275	# convert counts to Pressure in Pa (Centaur + V2 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*100			# maximum samples to shift in cross-correlation (usually at 50 sps)

