alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'KENI Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'KENI.HDF.AV.01'	, 'sta_lat': 60.6413700	, 'sta_lon': -151.070200},
{'scnl':'KENI.HDF.AV.02'	, 'sta_lat': 60.6404567 , 'sta_lon': -151.070330},
{'scnl':'KENI.HDF.AV.03'	, 'sta_lat': 60.6406033	, 'sta_lon': -151.072020},
{'scnl':'KENI.HDF.AV.04'	, 'sta_lat': 60.6412000	, 'sta_lon': -151.073000},
{'scnl':'KENI.HDF.AV.05'	, 'sta_lat': 60.6415300	, 'sta_lon': -151.072000},
{'scnl':'KENI.HDF.AV.06'	, 'sta_lat': 60.6409167 , 'sta_lon': -151.071170},
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
 {'volcano': 'Spurr',  'v_lat': 61.29897,  'v_lon': -152.25122,  'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
     'seismic_scnl': ['SPCP.BHZ.AV.--','SPCL.BHZ.AV.--','SPU.BHZ.AV.--']},

 {'volcano': 'Redoubt',  'v_lat': 60.48576,  'v_lon': -152.74282,  'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
     'seismic_scnl': ['RDDF.BHZ.AV.--','RDDF.BHZ.AV.--','RDSO.BHZ.AV.--']},

{'volcano': 'Iliamna',  'v_lat': 60.03220,  'v_lon': -153.09002,  'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
    'seismic_scnl': ['ILSW.BHZ.AV.--','ILS.BHZ.AV.--','IVE.BHZ.AV.--']},

 {'volcano': 'Augustine',  'v_lat': 59.36107,  'v_lon': -153.42938,  'Azimuth_tolerance': 8, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
     'seismic_scnl': ['AUJA.BHZ.AV.--','AUJK.BHZ.AV.--','AUSS.BHZ.AV.--']},

 {'volcano': 'Fourpeaked', 'v_lat': 58.7625, 'v_lon': -153.6632,   'Azimuth_tolerance': 5, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
     'seismic_scnl': ['Q19K.BHZ.AV.--','KARR.BHZ.AV.--','KAHG.BHZ.AV.--']},

 {'volcano': 'Katmai', 'v_lat': 58.263132, 'v_lon': -155.148067,   'Azimuth_tolerance': 10, 'min_pa': 0.1, 'vmin':0.28, 'vmax':0.4,
     'seismic_scnl': ['MGLS.BHZ.AV.--','KABU.BHZ.AV.--','ACH.BHZ.AV.--']},
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.5  # minimum frequency for bandpass filter
f2		  = 8.0 # maximum frequency for bandpass filter

digouti   = (1/419430.0)/(0.0275)	# convert counts to Pressure in Pa (Q330 + Chap Vx2 mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*100			# maximum samples to shift in cross-correlation (usually at 50 sps)
