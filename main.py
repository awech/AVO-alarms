#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import warnings
from obspy import UTCDateTime
import sys_config

sys.dont_write_bytecode = True	# don't write .pyc files (probably slightly faster without this, but more cluttered)

# if run from a cron, write output to hourly file in the logs directory
if os.getenv('FROMCRON') == 'yep':
    file=sys_config.logs_dir+'/'+sys.argv[1]+'-'+UTCDateTime.now().strftime('%Y%m%d-%H')+'.out'
    os.system('touch {}'.format(file))
    f=open(file,'a')
    sys.stdout=sys.stderr=f

print('')
print('-----------------------------------------')

# check input arguments. 1st argument is config file, 2nd is time (optional, otherwise right now)
if len(sys.argv) == 1:		
	warnings.warn('Wrong input arguments. eg: alarm.py Pavlof_RSAM 201701020205')
	sys.exit()
if len(sys.argv) == 2:								# no time given, use current time
	T0=UTCDateTime.utcnow() 						# get current timestamp
	T0=UTCDateTime(T0.strftime('%Y-%m-%d %H:%M')) 	# round down to the nearest minute
else:												# time given, use it
	if len(sys.argv)==3:							# time given as single string (eg. 201705130301)
		T0 = sys.argv[2]
	elif len(sys.argv)==4:							# time given as 2 strings (eg. 20170513 03:01)
		T0='{}{}'.format(sys.argv[2],sys.argv[3])
	else:
		warnings.warn('Too many input arguments. eg: alarm.py Pavlof_RSAM 201701020205')
		sys.exit()		
	try:
		T0 = UTCDateTime(T0)
	except:
		warnings.warn('Needs end-time argument. eg: alarm.py Pavlof_RSAM 201701020205')
		sys.exit()
try:
	exec('import alarm_configs.{} as config'.format(sys.argv[1]))			# import the config file for the alarm you're running
	ALARM=__import__('alarm_codes.'+config.alarm_type)					# import alarm module specified in config file
	eval('ALARM.{}.run_alarm(config,T0)'.format(config.alarm_type))	# run the alarm
except:																# if error, send message to designated recipients
	print('Error...')
	import traceback
	from alarm_codes import utils
	b=traceback.format_exc()
	message = ''.join('{}\n'.format(a) for a in b.splitlines())
	message = '{}\n\n{}'.format(T0.strftime('%Y-%m-%d %H:%M'),message)
	subject=config.alarm_name+' error'
	attachment='alarm_aux_files/oops.jpg'
	utils.send_alert('Error',subject,message,attachment)

print(UTCDateTime.utcnow().strftime('%Y.%m.%d %H:%M:%S'))
print('-----------------------------------------')
print('')

if os.getenv('FROMCRON') == 'yep':
	f.close()

sys.exit()