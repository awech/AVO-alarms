alarm_type = 'Airwave'			# this designates which alarm module will be imported and executed
alarm_name = 'SDPI Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'SDPI.BDF.AV.01'	, 'sta_lat': 55.34900	, 'sta_lon': -160.47640},
{'scnl':'SDPI.BDF.AV.02'	, 'sta_lat': 55.34870	, 'sta_lon': -160.47683},
{'scnl':'SDPI.BDF.AV.03'	, 'sta_lat': 55.34934	, 'sta_lon': -160.47732},
{'scnl':'SDPI.BDF.AV.04'	, 'sta_lat': 55.34952	, 'sta_lon': -160.47661},
{'scnl':'SDPI.BDF.AV.05'	, 'sta_lat': 55.34922	, 'sta_lon': -160.47650},
{'scnl':'SDPI.BDF.AV.06'	, 'sta_lat': 55.34919	, 'sta_lon': -160.47710},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Pavlof',		'v_lat': 55.417622,	'v_lon': -161.893669, 	'Azimuth_tolerance': 8, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['PV6A.BDF.AV.--','PV6A.SHZ.AV.--','PN7A.BHZ.AV.--','PS4A.BHZ.AV.--']},
{'volcano':	'Veniaminof',	'v_lat': 56.195825,	'v_lon': -159.389536, 	'Azimuth_tolerance': 6, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['VNSS.EHZ.AV.--','VNFG.EHZ.AV.--','VNHG.EHZ.AV.--']},
{'volcano':	'Shishaldin',	'v_lat': 54.755856,	'v_lon': -163.969961, 	'Azimuth_tolerance': 5, 'min_pa': 0.4, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['SSBA.BHZ.AV.--','SSLN.BHZ.AV.--','BRPK.EHZ.AV.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 10.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(1e-2)	# convert counts to Pressure in Pa (Q330 + VDP-10 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_pa    = 0.3					# min absolute pressure value for a trigger
vmin 	  = 0.25				# minimum allowable trace velocity for detection (km/s)
vmax 	  = 0.60				# maximum allowable trace velocity for detection (km/s)
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)