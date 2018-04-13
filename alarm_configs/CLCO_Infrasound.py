alarm_type = 'Airwave'			# this designates which alarm module will be imported and executed
alarm_name = 'CLCO Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'CLCO1.BDF.AV.--'	, 'sta_lat': 52.7864125000	, 'sta_lon': -169.7229250000},
{'scnl':'CLCO2.BDF.AV.--'	, 'sta_lat': 52.7871866667	, 'sta_lon': -169.7244333330},
{'scnl':'CLCO3.BDF.AV.--'	, 'sta_lat': 52.7874600000	, 'sta_lon': -169.7210166667},
{'scnl':'CLCO4.BDF.AV.--'	, 'sta_lat': 52.7861266667	, 'sta_lon': -169.7203966667},
{'scnl':'CLCO5.BDF.AV.--'	, 'sta_lat': 52.7851866667	, 'sta_lon': -169.7250066667},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Bogoslof',		'v_lat': 53.9310,	'v_lon': -168.0360, 	'Azimuth_tolerance': 15, 'min_pa': 0.2, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['OKFG.BHZ.AV.--','MAPS.BHZ.AV.--','MSW.BHN.AV.--']},

{'volcano':	'Cleveland',	'v_lat': 52.8222,	'v_lon': -169.9464, 	'Azimuth_tolerance': 15, 'min_pa': 4.0, 'vmin':0.28, 'vmax':0.41,
		'seismic_scnl': ['CLES.BHZ.AV.--','CLCO.BHZ.AV.--']}
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.2  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(1.62e-2)	# convert counts to Pressure in Pa (Q330 + new VDP-10 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)