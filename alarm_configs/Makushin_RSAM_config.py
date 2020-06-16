alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Makushin RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
#													    M4.5  M4.1  M3.9
SCNL=[
{'scnl':'MCIR.BHZ.AV.--'	, 'value':  2   * 1e3	}, # 55k , 31k ,  8k
{'scnl':'MGOD.BHZ.AV.--'	, 'value':  2   * 1e3	}, # 62k , 16k ,  8k
{'scnl':'MNAT.BHZ.AV.--'	, 'value':  2.25* 1e3	}, # 97k , 63k ,  9k
{'scnl':'MAPS.BHZ.AV.--'	, 'value':  0.25* 1e3	}, # 12k ,  4k ,  1k
{'scnl':'UNV.BHZ.AK.--'		, 'value':  1.25* 1e3	}, # 47k , 20k ,  5k
{'scnl':'AKGG.BHZ.AV.--'	, 'value':  20  * 1e3	}, # 73k , 57k , 13k arrestor station 
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

icinga_service_name = 'generic alarm 1'
# mattermost_channel_id = 'jewennqiq7rd5kdubg8t1j9b8a'