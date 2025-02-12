alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'WHTR Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
SCNL=[
{'scnl':'WHTR.HDF.AV.01'	, 'sta_lat': 60.77968	, 'sta_lon': -148.72701},
{'scnl':'WHTR.HDF.AV.02'	, 'sta_lat': 60.78018	, 'sta_lon': -148.72591},
{'scnl':'WHTR.HDF.AV.04'	, 'sta_lat': 60.77910	, 'sta_lon': -148.72658},
{'scnl':'WHTR.HDF.AV.05'	, 'sta_lat': 60.77970	, 'sta_lon': -148.72858},
{'scnl':'WHTR.HDF.AV.06'	, 'sta_lat': 60.78020	, 'sta_lon': -148.72739},
]

#SCNL=[
#{'scnl':'WHTR.HDF.AV.01'  , 'sta_lat': 60.77968 , 'sta_lon': -148.72701},
#{'scnl':'WHTR.HDF.AV.02'  , 'sta_lat': 60.78018 , 'sta_lon': -148.72591},
#{'scnl':'WHTR.HDF.AV.03'  , 'sta_lat': 60.77974 , 'sta_lon': -148.72533},
#{'scnl':'WHTR.HDF.AV.04'  , 'sta_lat': 60.77910 , 'sta_lon': -148.72658},
#{'scnl':'WHTR.HDF.AV.05'  , 'sta_lat': 60.77970 , 'sta_lon': -148.72858},
#{'scnl':'WHTR.HDF.AV.06'  , 'sta_lat': 60.78020 , 'sta_lon': -148.72739},
#]

# Volcano list to be monitored
# Need volcano name and location for each volcano
# Azimuthal tolerance is in degrees
# seismic_scnl is a list of seismic channels to be plotted with infrasound on detect
VOLCANO=[
{'volcano':	'Barry Arm',		'v_lat': 61.1457,	'v_lon': -148.14654, 	'Azimuth_tolerance': 8, 'min_pa': 1.0, 'vmin':0.28, 'vmax':0.45,
		'seismic_scnl': ['BAE.BHZ.AK.--','BAW.BHZ.AK.--','KNK.BHZ.AK.--']}
]

duration  = 3*60 # duration value in seconds
latency   = 5.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1		  = 0.5  # minimum frequency for bandpass filter
f2		  = 5 # maximum frequency for bandpass filter

digouti   = (1/400000)/0.0275	# convert counts to Pressure in Pa (Q330 + (VDP-10 pre Oct 15 2019) Chap Vx2 (post Oct 15 2019) mics)
min_cc    = 0.6					# min normalized correlation coefficient to accept
min_chan  = 3					# minimum # of channels for code to run
cc_shift_length = 6*100			# maximum samples to shift in cross-correlation (usually at 100 sps)

infrasound_plot_duration = 600
seismic_plot_duration = 600

# icinga_service_name = 'generic alarm 2'
mattermost_channel_id = 's9rog3p4ojypfr5xs3fciiecfa'
