alarm_type = 'Airwave'			# this designates which alarm module will be imported and executed
alarm_name = 'OK0 Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'OK01.BDF.AV.--'	, 'sta_lat': 53.41084	, 'sta_lon': -167.91431},
{'scnl':'OK02.BDF.AV.--'	, 'sta_lat': 53.41002	, 'sta_lon': -167.91367},
{'scnl':'OK03.BDF.AV.--'	, 'sta_lat': 53.40995	, 'sta_lon': -167.91505},
{'scnl':'OK04.BDF.AV.--'	, 'sta_lat': 53.41031	, 'sta_lon': -167.91440},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect 
VOLCANO=[
{'volcano':	'Bogoslof',		'v_lat': 53.9310,	'v_lon': -168.0360, 	'Azimuth_tolerance': 15, 'min_pa': 0.2, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['OKER.EHZ.AV.--','OKTU.EHZ.AV.--','MAPS.BHN.AV.--']},

{'volcano':	'Makushin',		'v_lat': 53.889210,	'v_lon': -166.925279, 	'Azimuth_tolerance': 6, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['MGOD.BHZ.AV.--','MREP.EHZ.AV.--','MAPS.BHN.AV.--']},

{'volcano':	'Cleveland',	'v_lat': 52.8222,	'v_lon': -169.9464, 	'Azimuth_tolerance': 3, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['CLES.BHZ.AV.--','CLCO.BHZ.AV.--']},

{'volcano':	'Okmok',		'v_lat': 53.428865,	'v_lon': -168.131632, 	'Azimuth_tolerance': 20, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.41,
		'seismic_scnl': ['OKNC.BHZ.AV.--','OKER.EHZ.AV.--']}
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.3  # minimum frequency for bandpass filter
# f1		  = 1.0  # temporary change on 20-Nov-2017 to remove microbarom false detects 
f2		  = 8.0  # maximum frequency for bandpass filter

digouti   = (1/419430.0)/0.05	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
min_cc    = 0.5					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)