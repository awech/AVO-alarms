alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'BAEI Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'BAEI.HDF.AV.01'	, 'sta_lat': 61.132675	, 'sta_lon': -148.1219},
{'scnl':'BAEI.HDF.AV.02'	, 'sta_lat': 61.132085	, 'sta_lon': -148.12107},
{'scnl':'BAEI.HDF.AV.03'	, 'sta_lat': 61.13173	, 'sta_lon': -148.121985},
{'scnl':'BAEI.HDF.AV.04'	, 'sta_lat': 61.131875	, 'sta_lon': -148.122915},
{'scnl':'BAEI.HDF.AV.05'	, 'sta_lat': 61.132405	, 'sta_lon': -148.12281},
{'scnl':'BAEI.HDF.AV.06'	, 'sta_lat': 61.13218	, 'sta_lon': -148.12206}
]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Barry Arm',		'v_lat': 61.141487,	'v_lon': -148.153993, 	'Azimuth_tolerance': 60, 'min_pa': 20.0, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['BAE.BHZ.AK.--','BAW.BHZ.AK.--','KNK.BHZ.AK.--']}
]

duration  = 90 # duration value in seconds
latency   = 5.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.5  # minimum frequency for bandpass filter
f2		  = 10 # maximum frequency for bandpass filter

digouti   = (1/400000)/0.0275	# convert counts to Pressure in Pa (Q330 + (VDP-10 pre Oct 15 2019) Chap Vx2 (post Oct 15 2019) mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 3*50			# maximum samples to shift in cross-correlation (usually at 50 sps)

infrasound_plot_duration = 600
seismic_plot_duration = 600

icinga_service_name = 'generic alarm 4'
mattermost_channel_id = 's9rog3p4ojypfr5xs3fciiecfa'
# BAEI testing
# mattermost_channel_id = 's9rog3p4ojypfr5xs3fciiecfa'