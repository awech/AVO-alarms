alarm_type = 'Infrasound'		# this designates which alarm module will be imported and executed
alarm_name = 'AMKA Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'AMKA.HDF.AV.01'	, 'sta_lat': 51.379251	, 'sta_lon': 179.301254},
{'scnl':'AMKA.HDF.AV.02'	, 'sta_lat': 51.378508	, 'sta_lon': 179.301857},
{'scnl':'AMKA.HDF.AV.03'	, 'sta_lat': 51.378079	, 'sta_lon': 179.301171},
{'scnl':'AMKA.HDF.AV.04'	, 'sta_lat': 51.378409	, 'sta_lon': 179.299999},
{'scnl':'AMKA.HDF.AV.05'	, 'sta_lat': 51.379032	, 'sta_lon': 179.300297},
{'scnl':'AMKA.HDF.AV.06'	, 'sta_lat': 51.37868	, 'sta_lon': 179.300981},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Little Sitkin',				'v_lat': 51.95,	'v_lon': 178.543, 	'Azimuth_tolerance':  4, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['LSSA.BHZ.AV.--','LSNW.BHZ.AV.--','LSPA.BHZ.AV.--','LSSE.BHZ.AV.--']},

{'volcano':	'Semisopochnoi',	'v_lat': 51.93,	'v_lon': 179.58, 	'Azimuth_tolerance':   7, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['CERB.BHZ.AV.--','CESW.BHZ.AV.--','CEPE.BHZ.AV.--','CERA.BHZ.AV.--','CETU.BHZ.AV.--']},

{'volcano':	'Central Aleutians',	'v_lat': 52.076,	'v_lon': -176.13, 	'Azimuth_tolerance':   7, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['KOKV.BHZ.AV.--','GSTD.BHZ.AV.--','KIKV.BHZ.AV.--','TASE.BHZ.AV.--','GAEA.BHZ.AV.--']},

]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.4  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/400000)/0.0275	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)

mattermost_channel_id = 'jewennqiq7rd5kdubg8t1j9b8a'