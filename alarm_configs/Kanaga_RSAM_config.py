alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Kanaga RSAM'		# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
#													    M2.8 (AEC)
SCNL=[
{'scnl':'KIWB.BHZ.AV.--'	, 'value':  650		}, # 4.7k
{'scnl':'KIKV.BHZ.AV.--'	, 'value':  875		}, # 37.5k
{'scnl':'KICM.BHN.AV.--'	, 'value': 1350		}, # 33.7k
{'scnl':'KIRH.BHZ.AV.--'	, 'value':  850		}, # 6.5k
{'scnl':'KIMD.BHZ.AV.--'	, 'value':  350		}, # 3.8k 
{'scnl':'ETKA.BHZ.AV.--'	, 'value':  200		}, # 0.17k arrestor station 
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 4    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

plot_duration = 1800

icinga_service_name = 'generic alarm 1'
# mattermost_channel_id = 'jewennqiq7rd5kdubg8t1j9b8a'

VOLCANO_NAME = 'Kanaga'