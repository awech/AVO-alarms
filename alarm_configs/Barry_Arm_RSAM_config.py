alarm_type = 'RSAM'				# this designates which alarm module will be imported and executed
alarm_name = 'Barry Arm RSAM'	# this is the alarm name sent to icinga and in message alerts

# Stations list. Last station is arrestor.
SCNL=[
{'scnl':'GLI.BHZ.AK.--'	, 'value':  500	},
{'scnl':'KNK.BHZ.AK.--'	, 'value':  1000	},
{'scnl':'PWL.BHZ.AK.--' , 'value':  500        },
{'scnl':'SKN.BHZ.AK.--'	, 'value':  100		}, # arrestor station
]

duration  = 5*60 # duration value in seconds
latency   = 10   # seconds between timestamps and end of data window
min_sta   = 2    # minimum number of stations for detection
taper_val = 5 	 # seconds to taper beginning and end of trace before filtering
f1		  = 1.0  # minimum frequency for bandpass filter
f2		  = 5.0  # maximum frequency for bandpass filter

icinga_service_name = 'generic alarm 1'
mattermost_channel_id = 's9rog3p4ojypfr5xs3fciiecfa'
plot_duration = 600
