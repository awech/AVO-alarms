alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Takawangha RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
#													    M2.8 (AEC)
SCNL=[
{'scnl':'TANO.BHZ.AV.--'	, 'value':  4.8 * 1e3	}, # 4.7k
{'scnl':'TASO.BHZ.AV.--'	, 'value':  6   * 1e3	}, # 7.9k
{'scnl':'TASE.BHZ.AV.--'	, 'value':  30  * 1e3	}, # 37.5k
{'scnl':'TAFP.BHN.AV.--'	, 'value':  30  * 1e3	}, # 33.7k
{'scnl':'TAPA.BHZ.AV.--'	, 'value':  6.5 * 1e3	}, # 6.5k
{'scnl':'TAFL.BHZ.AV.--'	, 'value':  3.9 * 1e3	}, # 3.8k 
# {'scnl':'KIMD.BHZ.AV.--'	, 'value':  0.3 * 1e3	}, # 0.17k arrestor station 
# {'scnl':'ADAG.BHZ.AV.--'	, 'value':  0.3 * 1e3	}, # 0.17k arrestor station 
{'scnl':'ETKA.BHZ.AV.--'	, 'value':  0.3 * 1e3	}, # 0.17k arrestor station 
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 4    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

icinga_service_name = 'generic alarm 3'
# mattermost_channel_id = 'jewennqiq7rd5kdubg8t1j9b8a'