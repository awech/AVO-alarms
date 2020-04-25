# This module contains all of the common functions that various alarms will use:
#	grab_data 		- gets data from a winston
#	icinga_state 	- sends heartbeat info to icinga
#	send_alert 		- does the actual email/txt message sending
#	post_mattermost - posts message to mattermost
#
# Wech, updated 2020-04-22

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from obspy import Trace
from numpy import zeros, round, dtype
from obspy import Stream
from obspy.clients.earthworm import Client
from pandas import read_excel
from tomputils import mattermost as mm
from obspy import UTCDateTime
from PIL import Image
import time
import re
import os
import subprocess


def grab_data(scnl,T1,T2,fill_value=0):
	# scnl = list of station names (eg. ['PS4A.EHZ.AV.--','PVV.EHZ.AV.--','PS1A.EHZ.AV.--'])
	# T1 and T2 are start/end obspy UTCDateTimes
	# fill_value can be 0 (default), 'latest', or 'interpolate'
	#
	# returns stream of traces with gaps accounted for
	#
	print('{} - {}'.format(T1.strftime('%Y.%m.%d %H:%M:%S'),T2.strftime('%Y.%m.%d %H:%M:%S')))
	print('Grabbing data...')

	st=Stream()

	for sta in scnl:
		if sta.split('.')[2]=='MI':
			client = Client(os.environ['CNMI_WINSTON'], int(os.environ['CNMI_PORT']))
		else:
			client = Client(os.environ['WINSTON_HOST'], int(os.environ['WINSTON_PORT']))
		try:
			tr=client.get_waveforms(sta.split('.')[2], sta.split('.')[0],sta.split('.')[3],sta.split('.')[1], T1, T2, cleanup=True)
			if len(tr)>1:
				if fill_value==0 or fill_value==None:
					tr.detrend('demean')
					tr.taper(max_percentage=0.01)
				for sub_trace in tr:
					# deal with error when sub-traces have different dtypes
					if sub_trace.data.dtype.name != 'int32':
						sub_trace.data=sub_trace.data.astype('int32')
					if sub_trace.data.dtype!=dtype('int32'):
						sub_trace.data=sub_trace.data.astype('int32')
					# deal with rare error when sub-traces have different sample rates
					if sub_trace.stats.sampling_rate!=round(sub_trace.stats.sampling_rate):
						sub_trace.stats.sampling_rate=round(sub_trace.stats.sampling_rate)
				print('Merging gappy data...')
				tr.merge(fill_value=fill_value)
		except:
			tr=Stream()
		# if no data, create a blank trace for that channel
		if not tr:
			tr=Trace()
			tr.stats['station']=sta.split('.')[0]
			tr.stats['channel']=sta.split('.')[1]
			tr.stats['network']=sta.split('.')[2]
			tr.stats['location']=sta.split('.')[3]
			tr.stats['sampling_rate']=100
			tr.stats['starttime']=T1
			tr.data=zeros(int((T2-T1)*tr.stats['sampling_rate']),dtype='int32')
		st+=tr
	print('Detrending data...')
	st.detrend('demean')
	st.trim(T1,T2,pad=0)
	return st


def icinga_state(config,state,state_message):

	print('Sending state and message to icinga:')

	states={      'OK': 0,
			 'WARNING': 1,
			'CRITICAL': 2,
			 'UNKNOWN': 3}

	state_num=states[state]

	#### which icinga service ####
	##############################
	if hasattr(config,'icinga_service_name'):
		icinga_service_name=config.icinga_service_name
	else:
		icinga_service_name=config.alarm_name
	##############################
	##############################


	cmd='echo "{}\t{}\t{}\t{}\\n" | {} -H {} -c {}'.format(os.environ['ICINGA_HOST_NAME'],icinga_service_name,state_num,
																state_message,os.environ['SEND_NSCA_CMD'],
																os.environ['ICINGA_IP'],os.environ['SEND_NSCA_CFG'])
	print(cmd)
	try:
		output=subprocess.check_output(cmd,shell=True)
	except:
		time.sleep(1.5)
		output=subprocess.check_output(cmd,shell=True)
	print(output)

	return


def send_alert(alarm_name,subject,body,filename=None):

	print('Sending alarm email and sms...')

	# read & parse notification list
	A=read_excel('distribution.xlsx')

	for recipient_group in ['x','o']:
		# filter to appropriate recipients
		recipients=A[A[alarm_name]==recipient_group]['Email'].tolist()
		if not recipients:
			continue
	 
		msg = MIMEMultipart()

		fromaddr=alarm_name.replace(' ','_')+'@usgs.gov'
		msg['From'] = fromaddr
		msg['Subject'] = subject
		if recipient_group=='x':
			msg['To'] = ', '.join(recipients)
		elif recipient_group=='o':
			msg['bcc'] = ', '.join(recipients)
		 
		msg.attach(MIMEText(body, 'plain'))
		
		if filename:
			name = filename.split('/')[-1]
			attachment = open(filename, "rb")
			part = MIMEBase('application', 'octet-stream')
			part.set_payload((attachment).read())
			encoders.encode_base64(part)
			part.add_header('Content-Disposition', 'attachment; filename= {}'.format(name))
			msg.attach(part)

		server = smtplib.SMTP(os.environ['SMTP_IP'])
		text = msg.as_string()
		server.sendmail(fromaddr, recipients, text)
		server.quit()


def post_mattermost(config,subject,body,filename=None):

	conn = mm.Mattermost(timeout=5,retries=4)

	if hasattr(config,'mattermost_channel_id'):
		conn.channel_id=config.mattermost_channel_id
	else:
		conn.channel_id=os.environ['MATTERMOST_DEFAULT_CHANNEL_ID']

	if not filename:
		files=[]
	else:
		files=[filename]


	p = re.compile('\\n(.*)\*(:.*)', re.MULTILINE)
	body = p.sub(r'\n- [x] __***\1\2***__', body)
	p = re.compile('\\n([A-Z,1-9]{3,4}:.*/.*)',re.MULTILINE)
	body = p.sub(r'\n- [ ] \1', body)

	body=body.replace('Start: ','Start:  ')
	body=body.replace('End: ',  'End:    ')

	if config.alarm_name!='PIREP':
		subject=subject.replace('--- ','')
		subject=subject.replace(' ---','')
		message='### **{}**\n\n{}'.format(subject,body)
	else:
		if 'URGENT' in subject:
			message='### **{}**\n\n{}'.format(subject,body)
		else:
			message='#### **{}**\n\n{}'.format(subject,body)

	try:
		conn.post(message, file_paths=files)
	except:
		conn.post(message, file_paths=files)


def save_file(plt,config,dpi=250):
	png_file=''.join([os.environ['TMP_FIGURE_DIR'],
					  '/',
					  config.alarm_name.replace(' ','_'),
					  '_',
					  UTCDateTime.utcnow().strftime('%Y%m%d_%H%M'),
					  '.png'])
	jpg_file=png_file.split('.')[0]+'.jpg'

	plt.savefig(png_file,dpi=dpi,format='png')
	im=Image.open(png_file)
	im.convert('RGB').save(jpg_file,'JPEG')
	os.remove(png_file)

	return jpg_file