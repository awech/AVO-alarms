alarm_type = 'Infrasound'		# this designates which alarm module will be imported and executed
alarm_name = 'ADKI Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'ADKI.HDF.AV.01'	, 'sta_lat': 51.86190727	, 'sta_lon': -176.6438598},
{'scnl':'ADKI.HDF.AV.02'	, 'sta_lat': 51.86324162	, 'sta_lon': -176.6435998},
{'scnl':'ADKI.HDF.AV.03'	, 'sta_lat': 51.86226962	, 'sta_lon': -176.6446503},
{'scnl':'ADKI.HDF.AV.04'	, 'sta_lat': 51.86246609	, 'sta_lon': -176.6457851},
{'scnl':'ADKI.HDF.AV.05'	, 'sta_lat': 51.86326916	, 'sta_lon': -176.6461231},
# {'scnl':'ADKI.HDF.AV.06'	, 'sta_lat': 51.86157572	, 'sta_lon': -176.6469340},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Moffett',				'v_lat': 51.931876,	'v_lon': -176.740191, 	'Azimuth_tolerance':  15, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['ADK.BHZ.IU.--','ADAG.BHZ.AV.--']},

{'volcano':	'Central Aleutians',	'v_lat': 52.8222,	'v_lon': -169.9464, 	'Azimuth_tolerance':   8, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['KOKV.BHZ.AV.--','CLES.BHZ.AV.--','OKNC.BHZ.AV.--','MAPS.BHZ.AV.--'], 'traveltime':False},

{'volcano':	'Western Aleutians',	'v_lat': 52.029530,	'v_lon': 178.231398, 	'Azimuth_tolerance':  10, 'min_pa': 0.5, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['LSSE.BHZ.AV.--','CEPE.BHZ.AV.--','GANO.BHZ.AV.--','TASE.BHZ.AV.--','KIKV.BHZ.AV.--'], 'traveltime':False},

{'volcano':	'Great Sitkin',			'v_lat': 52.077282,	'v_lon': -176.131317, 	'Azimuth_tolerance':   7, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['GSTD.BHZ.AV.--','GSSP.BHZ.AV.--','GSTR.BHZ.AV.--','GSMY.BHZ.AV.--','GSCK.BHZ.AV.--']},

{'volcano':	'Bogoslof',				'v_lat': 53.9310,	'v_lon': -168.0360, 	'Azimuth_tolerance': 1.5, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.43,
		'seismic_scnl': ['OKNO.BHZ.AV.--','OKTU.BHZ.AV.--','MAPS.BHN.AV.--']},

{'volcano':	'Makushin',		'v_lat': 53.8900,	'v_lon': -166.9200, 	'Azimuth_tolerance': 8, 'min_pa': 0.3, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['MCIR.BHZ.AV.--','MGOD.BHZ.AV.--','MNAT.BHN.AV.--']},

{'volcano':	'Shishaldin',	'v_lat': 54.755856,	'v_lon': -163.969961, 	'Azimuth_tolerance': 5, 'min_pa': 0.3, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['SSBA.BHZ.AV.--','ISNN.BHZ.AV.--','WTUG.BHZ.AV.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.4  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(0.05)	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 6*100			# maximum samples to shift in cross-correlation (usually at 100 sps)
