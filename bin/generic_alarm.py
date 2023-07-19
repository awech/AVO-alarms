#!/home/rtem/.conda/envs/alarms2/bin/python
# -*- coding: utf-8 -*-

import sys
sys.path.append('/alarms')
from alarm_codes import utils

def config():
	return

alarm_name=sys.argv[1].replace('_',' ')
config.icinga_service_name=alarm_name
config.alarm_name=alarm_name

state='OK'
state_message='Empty alarm service'

# utils.icinga_state(config,state,state_message)
utils.icinga2_state(config, state, state_message)