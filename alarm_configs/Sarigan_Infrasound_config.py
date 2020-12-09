alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'Sarigan Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'SRN1.BDF.MI.--'	, 'sta_lat': 16.70035	, 'sta_lon': 145.77809},
{'scnl':'SRN2.BDF.MI.--'	, 'sta_lat': 16.69977	, 'sta_lon': 145.77798},
{'scnl':'SRN3.BDF.MI.--'	, 'sta_lat': 16.69960	, 'sta_lon': 145.77841},
{'scnl':'SRN4.BDF.MI.--'	, 'sta_lat': 16.69990	, 'sta_lon': 145.77876},
# {'scnl':'SRN5.BDF.MI.--'	, 'sta_lat': 16.70036	, 'sta_lon': 145.77872},
{'scnl':'SRN6.BDF.MI.--'	, 'sta_lat': 16.70003	, 'sta_lon': 145.77838},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'South (Anatahan?)','v_lat': 16.351323,	'v_lon': 145.687602, 	'Azimuth_tolerance': 15, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['ANNE.BHZ.MI.--','ANLB.BHZ.MI.--','DPS.BHZ.MI.--','GOLF.BHZ.MI.--']},
{'volcano':	'North (Pagan?)',	'v_lat': 18.141555,	'v_lon': 145.786260, 	'Azimuth_tolerance': 15, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['ANNE.BHZ.MI.--','ANLB.BHZ.MI.--','DPS.BHZ.MI.--','GOLF.BHZ.MI.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 200.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(1e-2)	# convert counts to Pressure in Pa (Q330 + VDP-10 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 4					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)