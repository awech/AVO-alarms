alarm_type = 'Infrasound'		# this designates which alarm module will be imported and executed
alarm_name = 'DLL Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'DLL.HDF.AV.01'	, 'sta_lat': 59.13988781	, 'sta_lon': -158.6209290},
{'scnl':'DLL.HDF.AV.02'	, 'sta_lat': 59.13620003	, 'sta_lon': -158.6053376},
{'scnl':'DLL.HDF.AV.03'	, 'sta_lat': 59.12904044	, 'sta_lon': -158.6146964},
{'scnl':'DLL.HDF.AV.04'	, 'sta_lat': 59.13602776	, 'sta_lon': -158.6142354},
{'scnl':'DLL.HDF.AV.05'	, 'sta_lat': 59.13509488	, 'sta_lon': -158.6136803},
{'scnl':'DLL.HDF.AV.06'	, 'sta_lat': 59.13532733	, 'sta_lon': -158.6155527},
]


# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect 
VOLCANO=[
{'volcano':	'Semisopochnoi',	'v_lat': 51.947,	'v_lon': 179.623, 	'Azimuth_tolerance': 8, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['CERB.SHZ.AV.--','CESW.SHZ.AV.--','CEAP.SHZ.AV.--']},

# {'volcano':	'Spurr',	'v_lat': 61.29897,	'v_lon': -152.25122, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

# {'volcano':	'Redoubt',	'v_lat': 60.48576,	'v_lon': -152.74282, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

{'volcano':	'Iliamna',	'v_lat': 60.03220,	'v_lon': -153.09002, 	'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['ILSW.BHZ.AV.--','ILS.BHZ.AV.--','IVE.BHZ.AV.--']},

# {'volcano':	'Augustine',	'v_lat': 59.36107,	'v_lon': -153.42938, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

# {'volcano':	'Fourpeaked',	'v_lat': 58.7625,	'v_lon': -153.6632, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

# {'volcano':	'Katmai',	'v_lat': 58.3313,	'v_lon': -154.6716, 	'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

# {'volcano':	'Peulik',	'v_lat': 57.7475,	'v_lon': -156.37368, 	'Azimuth_tolerance': 4, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

# {'volcano':	'Aniakchak',	'v_lat': 56.89885,	'v_lon': -158.14768, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['ANON.EHZ.AV.--','ANNE.EHZ.AV.--','ANPK.EHZ.AV.--']},

{'volcano':	'Veniaminof',	'v_lat': 56.195825,	'v_lon': -159.389536, 	'Azimuth_tolerance': 2, 'min_pa': 3.0, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['VNSS.EHZ.AV.--','VNFG.EHZ.AV.--','VNHG.EHZ.AV.--']},

# {'volcano':	'Pavlof',		'v_lat': 55.417622,	'v_lon': -161.893669, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['PV6A.BDF.AV.--','PV6A.SHZ.AV.--','PN7A.BHZ.AV.--','PS1A.BHZ.AV.--']},

{'volcano':	'Shishaldin',	'v_lat': 54.755856,	'v_lon': -163.969961, 	'Azimuth_tolerance': 2, 'min_pa': 0.3, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['SSBA.BHZ.AV.--','SSLS.BHZ.AV.--','ISNN.SHZ.AV.--']},

# {'volcano':	'Bogoslof',		'v_lat': 53.9310,	'v_lon': -168.0360, 	'Azimuth_tolerance': 2, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['OKER.EHZ.AV.--','OKTU.EHZ.AV.--','MAPS.BHN.AV.--']},

# {'volcano':	'Cleveland',	'v_lat': 52.8222,	'v_lon': -169.9464, 	'Azimuth_tolerance': 1, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.45,
# 		'seismic_scnl': ['CLES.BHZ.AV.--','CLCO.BHZ.AV.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 120.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
# f1		  = 0.3  # minimum frequency for bandpass filter
f1		  = 1.0  # temporary change on 20-Nov-2017 to remove microbarom false detects 
f2		  = 8.0  # maximum frequency for bandpass filter

# digouti   = (1/419430.0)/0.05	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
digouti   = 0.00000409476	# convert counts to Pressure in Pa (Q330 + Chaparral mics)
min_cc    = 0.5					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)