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
from obspy import Trace, Catalog
from numpy import zeros, round, dtype, cos, pi
from obspy import Stream
from obspy.clients.earthworm import Client
from pandas import read_excel, DataFrame
from tomputils import mattermost as mm
from obspy import UTCDateTime
from obspy.geodetics import gps2dist_azimuth
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

	t_test1=UTCDateTime.now()
	for sta in scnl:
		if sta.split('.')[2] in ['HV','AM']:
			client = Client(os.environ['NEIC_HOST'], int(os.environ['NEIC_PORT']), timeout=int(os.environ['TIMEOUT']))
		else:
			client = Client(os.environ['WINSTON_HOST'], int(os.environ['WINSTON_PORT']), timeout=int(os.environ['TIMEOUT']))
		try:
			tr=client.get_waveforms(sta.split('.')[2], sta.split('.')[0],sta.split('.')[3],sta.split('.')[1], T1, T2, cleanup=True)
			if len(tr)>1:
				print('{:.0f} traces for {}'.format(len(tr),sta))
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
	print('{} seconds'.format(UTCDateTime.now()-t_test1))
	
	print('Detrending data...')
	st.detrend('demean')
	st.trim(T1, T2, pad=True, fill_value=0)
	return st


def download_hypocenters(URL):
	import requests
	from obspy.io.quakeml.core import Unpickler
	import urllib3
	urllib3.disable_warnings()

	attempt = 1
	while attempt <= 3:
		try:
			res = requests.get(URL, verify=False, timeout=10)
			body = res.content
			break
		except:
			time.sleep(2)
			attempt+=1
			body = None

	if not body:
		return None	
	
	try:
		CAT = Unpickler().loads(body)
	except:
		CAT = Catalog()
		print('No events!')

	return CAT


def icinga2_state(config,state,state_message):
	import requests, json
	import urllib3
	urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

	print('Sending state and message to icinga2:')

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

	headers = {
			    'Accept': 'application/json',
			    'X-HTTP-Method-Override': 'POST'
			  }
	data = { 
			 'type': 'Service',
			 'filter': 'host.name==\"{}\" && service.name==\"{}\"'.format(os.environ['ICINGA_HOST_NAME'],icinga_service_name),
			 'exit_status': state_num,
			 'plugin_output': state_message
		   }

	try:
		resp = requests.get(os.environ['ICINGA2_URL'], 
							headers=headers, 
							auth=(os.environ['ICINGA2_USERNAME'], os.environ['ICINGA2_PASSWORD']), 
							data=json.dumps(data), 
							verify=False,
							timeout=10)
		if (resp.status_code == 200):
			print(resp.json()['results'][0]['status'])
			print('Success. Message sent to icinga2')
		else:
			print('Status code = {:g}'.format(resp.status_code))
			print('Failed to send message to icinga2')
	except:
		print('requests error. Failed to send message to icinga2')

	return


def volcano_distance(lon0, lat0, volcs):
	import numpy as np

	DIST = np.array([])
	for lat, lon in zip(volcs.Latitude.values, volcs.Longitude.values):
		dist, azimuth, az2 = gps2dist_azimuth(lat, lon, lat0, lon0)
		DIST = np.append(DIST, dist/1000.)
	volcs.loc[:, 'distance'] = DIST

	return volcs


def Dr_to_RSAM(config, DR, volcano_name, base=25):
	
	import numpy as np
	from obspy.clients.fdsn import Client
	client = Client("IRIS")

	
	VELOCITY = 1.5 	# km/s
	FREQ = 2 		# dominant frequency (Hz)
	Q = 200			# quality factor

	T0 = UTCDateTime.utcnow()
	VOLCS = read_excel('alarm_aux_files/volcano_list.xlsx')
	volcs = VOLCS[VOLCS['Volcano'] == volcano_name].copy()
	SCNL = DataFrame.from_dict(config.SCNL)

	for scnl in SCNL.scnl:

		sta, chan, net, loc = scnl.split('.')
		inventory = client.get_stations(network=net, 
									station=sta,
									channel=chan,
									location=loc,
									starttime=T0,
									endtime=T0,
									level='response')
		
		tr_id = '.'.join((net, sta, loc, chan)).replace('--', '')
		coords = inventory.get_coordinates(tr_id)
		gain = inventory.get_response(tr_id,T0).instrument_sensitivity.value # counts/m/s

		volcs = volcano_distance(coords['longitude'], coords['latitude'], volcs)
		R = volcs.iloc[0].distance


		# distance, velocity and wavelength in cm
		r = R * 1000 * 100
		velocity = VELOCITY * 1000 * 100
		wavelength = velocity / FREQ


		#### account for attenuation ####
		numerator = -np.pi * FREQ * r
		denominator = Q * velocity
		atten_factor = np.exp(numerator / denominator)


		rmssta = DR / np.sqrt(r * wavelength) 			# rms in cm
		rmssta_v = (rmssta * 2 * np.pi * FREQ) / 100 	# convert to velocity and change from cm to m (for the gain)
		lvl = rmssta_v * gain * atten_factor			# use gain to turn m/s to counts, and apply attenuation

		lvl = base * round(lvl / base)

		print('{}: {:g}'.format(scnl, lvl))

	return


def send_alert(alarm_name,subject,body,filename=None):

	print('Sending alarm email and sms...')

	# read & parse notification list
	distribution_file=''.join([os.environ['HOME_DIR'],'/','distribution.xlsx'])
	A=read_excel(distribution_file)

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

		server = smtplib.SMTP_SSL(host=os.environ['SMTP_IP'], port=os.environ['SMTP_PORT'] )
		# server = smtplib.SMTP(os.environ['SMTP_IP'])
		text = msg.as_string()
		server.sendmail(fromaddr, recipients, text)
		server.quit()

	return


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

	return

def make_map(ax,lat0,lon0,main_dist=50,inset_dist=500,scale=15):
	from mpl_toolkits.basemap import Basemap
	from mpl_toolkits.axes_grid1.inset_locator import inset_axes

	dlat=1*(main_dist/111.1)
	dlon=dlat/cos(lat0*pi/180)
	latmin= lat0 - dlat
	latmax= lat0 + dlat
	lonmin= lon0 - dlon
	lonmax= lon0 + dlon

	m_map = Basemap(projection='merc',llcrnrlat=latmin,urcrnrlat=latmax,
							  llcrnrlon=lonmin,urcrnrlon=lonmax,lat_ts=lat0,resolution='h')		


	land_color='silver'
	water_color='lightblue'
	try:
		m_map.drawcoastlines(linewidth=0.5)
	except:
		pass
	m_map.drawmapboundary(fill_color=water_color)
	m_map.fillcontinents(color=land_color,lake_color=water_color)
	m_map.drawparallels([lat0-dlat/2,lat0+dlat/2],labels=[0,1,0,0],dashes=[8, 4],linewidth=0.2,fmt='%.2f',fontsize=6)
	m_map.drawmeridians([lon0-dlon/2,lon0+dlon/2],labels=[0,0,0,1],dashes=[8, 4],linewidth=0.2,fmt='%.2f',fontsize=6)
	m_map.drawmapscale(lon0-.7*dlon, lat0-.8*dlat, lon0, lat0, scale, barstyle='simple', units='km', fontsize=8, 
				    labelstyle='simple', fontcolor='k', linewidth=0.5, ax=None, format='%d', zorder=None)

	m_map.ax = ax

	# Inset map.
	axin = inset_axes(m_map.ax, width="25%", height="25%", loc=1,borderpad=-1.5)

	dlat=1.75*(inset_dist/111.1)
	dlon=2*dlat/cos(lat0*pi/180)
	latmin= lat0 - dlat
	latmax= lat0 + dlat
	lonmin= lon0 - dlon
	lonmax= lon0 + dlon


	inmap = Basemap(projection='merc',llcrnrlat=latmin,urcrnrlat=latmax,
							  llcrnrlon=lonmin,urcrnrlon=lonmax,lat_ts=lat0,resolution='i',area_thresh=50.0)		

	inmap.drawcoastlines(linewidth=0.2)
	inmap.drawcountries(color='0.2',linewidth=0.2)
	inmap.fillcontinents(color=land_color)
	inmap.drawmapboundary(color='black',fill_color=water_color,linewidth=0.5)
	inmap.fillcontinents(color=land_color,lake_color=water_color)

	inmap.ax=axin

	return m_map, inmap


def save_file(plt,config,dpi=250):
	png_file=''.join([os.environ['TMP_FIGURE_DIR'],
					  '/',
					  config.alarm_name.replace(' ','_'),
					  '_',
					  UTCDateTime.utcnow().strftime('%Y%m%d_%H%M%S'),
					  '.png'])
	jpg_file=png_file.split('.')[0]+'.jpg'

	plt.savefig(png_file,dpi=dpi,format='png')
	im=Image.open(png_file)
	im.convert('RGB').save(jpg_file,'JPEG')
	os.remove(png_file)

	return jpg_file