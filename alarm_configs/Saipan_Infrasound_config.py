alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'Saipan Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'FLX2.BDF.MI.01'	, 'sta_lat': 15.23481	, 'sta_lon': 145.79219},
# {'scnl':'FLX2.BDF.MI.02'	, 'sta_lat': 15.23325	, 'sta_lon': 145.79242}, # dead channels. changed 23-Oct-2020
{'scnl':'FLX2.BDF.MI.03'	, 'sta_lat': 15.23461	, 'sta_lon': 145.79097},
# {'scnl':'FLX2.BDF.MI.04'	, 'sta_lat': 15.23206	, 'sta_lon': 145.79389}, # dead channels. changed 23-Oct-2020
{'scnl':'FLX2.BDF.MI.05'	, 'sta_lat': 15.23217	, 'sta_lon': 145.79119},
{'scnl':'FLX2.BDF.MI.06'	, 'sta_lat': 15.23650	, 'sta_lon': 145.79053},
# {'scnl':'DPS.BDF.MI.--'		, 'sta_lat': 15.24082	, 'sta_lon': 145.78909},
# {'scnl':'HTSP.BDF.MI.--'	, 'sta_lat': 15.23166	, 'sta_lon': 145.79851},
# {'scnl':'GOLF.BDF.MI.--'	, 'sta_lat': 15.22511	, 'sta_lon': 145.78625}, # still has IML sensor
# {'scnl':'FLX.BDF.MI.--'		, 'sta_lat': 15.23389	, 'sta_lon': 145.79172},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'North (Anatahan?)',	'v_lat': 18.141555,	'v_lon': 145.786260, 	'Azimuth_tolerance': 15, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['ANNE.BHZ.MI.--','ANLB.BHZ.MI.--','DPS.BHZ.MI.--','GOLF.BHZ.MI.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 180.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(1e-2)	# convert counts to Pressure in Pa (Q330 + VDP-10 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 4					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)