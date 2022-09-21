alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Tau RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
#													    
SCNL=[
{'scnl':'TAU.HHZ.HV.--'	, 'value':      7   * 1e3	}, # 
{'scnl':'OFU.HHZ.HV.--'	, 'value':      3   * 1e3	}, # 
{'scnl':'FAGA.HHZ.HV.--'	, 'value':  7   * 1e3	}, # 
{'scnl':'R3112.EHZ.AM.00'	, 'value':  6   * 1e3	}, # 
{'scnl':'R532B.EHZ.AM.00'	, 'value':  8   * 1e3	}, # 
# {'scnl':'R49B7.EHZ.AM.00'	, 'value':  10  * 1e3	}, # 
{'scnl':'RAA63.EHZ.AM.00'	, 'value':  8  * 1e3	}, # 
# {'scnl':'R4464.EHZ.AM.00'	, 'value':  4  * 1e3	}, #  arrestor station 
{'scnl':'JEFF.BFD.AM.--'	, 'value':  4  * 1e3	}, #  arrestor station 
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 3    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

plot_duration = 1800

icinga_service_name = 'generic alarm 3'
mattermost_channel_id = 'b9gws86whib65caeoagy4ykhbh'