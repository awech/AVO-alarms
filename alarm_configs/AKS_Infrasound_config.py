alarm_type = 'Infrasound'		# this designates which alarm module will be imported and executed
alarm_name = 'AKS Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
# SCNL=[
# {'scnl':'AKS.BDF.AV.01'	, 'sta_lat': 54.11050	, 'sta_lon': -165.69773},
# {'scnl':'AKS.BDF.AV.02'	, 'sta_lat': 54.11028	, 'sta_lon': -165.69618},
# {'scnl':'AKS.BDF.AV.03'	, 'sta_lat': 54.11105	, 'sta_lon': -165.69700},
# {'scnl':'AKS.BDF.AV.04'	, 'sta_lat': 54.11053	, 'sta_lon': -165.69683},
# ]

SCNL=[
{'scnl':'AKS.HDF.AV.01'	, 'sta_lat': 54.11048	, 'sta_lon': -165.69774},
{'scnl':'AKS.HDF.AV.02'	, 'sta_lat': 54.11105	, 'sta_lon': -165.69705},
{'scnl':'AKS.HDF.AV.03'	, 'sta_lat': 54.11028	, 'sta_lon': -165.69616},
{'scnl':'AKS.HDF.AV.04'	, 'sta_lat': 54.11051	, 'sta_lon': -165.69681},
# {'scnl':'AKS.HDF.AV.04'	, 'sta_lat': 54.11051	, 'sta_lon': -165.69683},
{'scnl':'AKS.HDF.AV.06'	, 'sta_lat': 54.11005	, 'sta_lon': -165.69720},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect 
VOLCANO=[
{'volcano':	'Alaska Peninsula',	'v_lat': 54.755856,	'v_lon': -163.969961, 	'Azimuth_tolerance': 10, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['WESE.BHZ.AV.--','SSBA.BHZ.AV.--','PN7A.BHZ.AV.--']},

{'volcano':	'Akutan',		'v_lat': 54.143600,	'v_lon': -165.977736, 	'Azimuth_tolerance': 10, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['AKSA.BHZ.AV.--','AKRB.BHZ.AV.--','ZRO.BHZ.AV.--']},

{'volcano':	'Makushin',		'v_lat': 53.889210,	'v_lon': -166.925279, 	'Azimuth_tolerance': 5.5, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['MGOD.BHZ.AV.--','MREP.BHZ.AV.--','MAPS.BHN.AV.--']},

{'volcano':	'Okmok',		'v_lat': 53.428865,	'v_lon': -168.131632, 	'Azimuth_tolerance': 3.5, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.41,
		'seismic_scnl': ['OKNC.BHZ.AV.--','OKER.BHZ.AV.--','OKTU.BHZ.AV.--']}
]

duration  = 3*60 # duration value in seconds
latency   = 15.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
# f1		  = 0.3  # minimum frequency for bandpass filter
f1		  = 1.0  # temporary change on 20-Nov-2017 to remove microbarom false detects 
f2		  = 8.0  # maximum frequency for bandpass filter

# digouti   = (1/419430.0)/0.05	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
digouti   = (1/400000)/0.0275	# convert counts to Pressure in Pa (Centaur + Chaparral Vx2 mics)
min_cc    = 0.5					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 6*100			# maximum samples to shift in cross-correlation (usually at 100 sps)
