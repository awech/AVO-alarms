#!/home/rtem/miniconda/envs/py_alarms/bin/python
# -*- coding: utf-8 -*-

# alarm_codes is a directory
# utils is file. Importing it allows for error email delivery & importing environment variables
from alarm_codes import utils
from obspy import UTCDateTime
import os
import sys
import traceback
import warnings

# don't write .pyc files (probably slightly faster without this, but more cluttered)
sys.dont_write_bytecode = True

# if run from a cron, write output to 4-hourly file in the logs directory
if os.getenv('FROMCRON') == 'yep':
	T0=UTCDateTime.now()
	d_hour=int(T0.strftime('%H'))%4
	f_time=UTCDateTime(T0.strftime('%Y%m%d'))+(int(T0.strftime('%H'))-d_hour)*3600
	file=os.environ['LOGS_DIR']+'/'+sys.argv[1]+'-'+f_time.strftime('%Y%m%d-%H')+'.out'
	os.system('touch {}'.format(file))
	f=open(file,'a')
	sys.stdout=sys.stderr=f

print('')
print('-----------------------------------------')

# check input arguments. 1st argument is config file, 2nd is time (optional, otherwise right now)
if len(sys.argv) == 1:		
	warnings.warn('Wrong input arguments. eg: main.py Pavlof_RSAM 201701020205')
	sys.exit()

# no time given, use current time
if len(sys.argv) == 2:
	# get current timestamp
	T0=UTCDateTime.utcnow()
	# round down to the nearest minute
	T0=UTCDateTime(T0.strftime('%Y-%m-%d %H:%M'))
# time given, use it
else:
	# time given as single string (eg. 201705130301)
	if len(sys.argv)==3:
		T0 = sys.argv[2]
	# time given as 2 strings (eg. 20170513 03:01)
	elif len(sys.argv)==4:
		T0='{}{}'.format(sys.argv[2],sys.argv[3])
	else:
		warnings.warn('Too many input arguments. eg: main.py Pavlof_RSAM 201701020205')
		sys.exit()		
	try:
		T0 = UTCDateTime(T0)
	except:
		warnings.warn('Needs end-time argument. eg: main.py Pavlof_RSAM 201701020205')
		sys.exit()
try:
	# import the config file for the alarm you're running
	exec('import alarm_configs.{} as config'.format(sys.argv[1]))
	# import alarm module specified in config file
	ALARM=__import__('alarm_codes.'+config.alarm_type)

	# run the alarm
	eval('ALARM.{}.run_alarm(config,T0)'.format(config.alarm_type))

# if error, send message to designated recipients
except:
	print('Error...')
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