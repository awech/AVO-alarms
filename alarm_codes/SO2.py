import requests
from bs4 import BeautifulSoup
import pandas as pd
from obspy import UTCDateTime
import os
from . import utils
from PIL import Image
from obspy.geodetics.base import gps2dist_azimuth


def run_alarm(config,T0):
	
	try:
		page = requests.get(os.environ['SACS_URL'],timeout=10)
		soup = BeautifulSoup(page.content, 'html.parser')
		table=soup.find_all('pre')[0]
	except:
		try:
			page = requests.get(os.environ['SACS_URL'],timeout=10)
			soup = BeautifulSoup(page.content, 'html.parser')
			table=soup.find_all('pre')[0]
		except:
			try:
				page = requests.get(os.environ['SACS_URL'],timeout=10)
				soup = BeautifulSoup(page.content, 'html.parser')
				table=soup.find_all('pre')[0]
			except:
				print('Page error.')
				state='WARNING'
				state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				utils.icinga_state(config,state,state_message)
				utils.icinga2_state(config,state,state_message)
				return

	try:
		table=table.get_text().split('\n')
		table=table[1:-1]

		date   = table[1].split(':')[-1].replace(' ','')
		time   = table[2].split(' :')[-1].split('UTC')[0].replace(' ','')
		lon    = float(table[3].split(':')[-1].split('deg')[0].replace(' ',''))
		lat    = float(table[4].split(':')[-1].split('deg')[0].replace(' ',''))
		# SZA    = table[4].split(':')[-1].split('deg')[0].replace(' ','')
		# SO2max = table[5].split(':')[-1].split('DU')[0].replace(' ','')
		# S02ht  = table[6].split(':')[-1].split('km')[0].replace(' ','')
	except:
		print('Page error.')
		state='WARNING'
		state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
		utils.icinga_state(config,state,state_message)
		utils.icinga2_state(config,state,state_message)	
		return	

	volcs = pd.read_excel(config.volc_file)
	volcs = volcs[volcs['SO2']=='Y']
	volcs = utils.volcano_distance(lon, lat, volcs)
	volcs = volcs.sort_values('distance')

	new_time = time_check(date,time,config)

	if new_time and volcs.distance.min()<config.max_distance:
		print('....New detection....')
		print('Downloading image')
		attachment = download_image(soup,config,date,time)
		print('Drafting alert')
		subject, message = create_message(date,time,table,config,volcs)
		print('Sending direct alert')
		utils.send_alert(config.alarm_name,subject,message,attachment)
		# update timestamp to avoid resending same alert
		update_timestamp(date,time,config)
		
		print('Posting to Mattermost')
		utils.post_mattermost(config,subject,message,filename=attachment)


		# delete the file you just sent
		if attachment:
			os.remove(attachment)

		state_message='{} (UTC) SO2 detection!'.format(T0.strftime('%Y-%m-%d %H:%M'))
		state='CRITICAL'
	elif volcs.distance.min()<config.max_distance and not new_time:
		state_message='{} (UTC) Old SO2 detection! [{}]'.format(T0.strftime('%Y-%m-%d %H:%M'),
																UTCDateTime(date + time).strftime('%Y-%m-%d %H:%M'))
		state='WARNING'
	else:
		state_message='{} (UTC) No new SO2 detections'.format(T0.strftime('%Y-%m-%d %H:%M'))
		state='OK'

	# send heartbeat status message to icinga
	utils.icinga_state(config,state,state_message)
	utils.icinga2_state(config,state,state_message)


def volcano_distance(lon,lat,config):
	volcs=pd.read_csv(config.volc_file,delimiter='\t',names=['Volcano','kml','Lon','Lat'])

	volcs['dist']=1e9
	for i,row in volcs.iterrows():
		dist, azimuth, az2=gps2dist_azimuth(row.Lat,row.Lon,lat,lon)
		volcs.loc[i,'dist']=dist/1000.

	return volcs

def time_check(date,time,config):
	t_current=UTCDateTime(date + time)
	t_file=open(r'{}'.format(config.outfile),'r')
	t_last=UTCDateTime(t_file.read())
	t_file.close()
	return t_last!=t_current

def download_image(soup,config,date,time):

	imgs=soup.find_all('img')
	img_files=[]
	for im in imgs:
		if '/alert' in im.get('src'):
			img_files.append(im.get('src'))
	
	if img_files:
		pic_url=os.environ['SACS_URL'].split('last')[0]+img_files[0]
		pic_url=pic_url.replace('_sm','_lr')
		img_data = requests.get(pic_url,stream=True).content
		gif_file=''.join([os.environ['TMP_FIGURE_DIR'],
					  '/',
					  config.alarm_name.replace(' ','_'),
					  '_',
					  UTCDateTime.utcnow().strftime('%Y%m%d_%H%M'),
					  '.gif'])
		jpg_file=gif_file.split('.')[0]+'.jpg'
		with open(gif_file, 'wb') as handler:
		    handler.write(img_data)

		try:
			im=Image.open(gif_file)
			os.remove(gif_file)
			im.convert('RGB').save(jpg_file,'JPEG')
			attachment=jpg_file
		except:
			attachment=[]
	else:
		attachment=[]

	return attachment


def update_timestamp(date,time,config):
	t_file=open(r'{}'.format(config.outfile),'w+')
	t_file.write(str(UTCDateTime(date + time)))
	t_file.close()

def create_message(date,time,table,config,volcs):

	subject = 'SO2 detection'

	t=pd.Timestamp(UTCDateTime(date + time).datetime,tz='UTC')
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'),t_local.tzname())
	UTC_time_text = '{} UTC'.format(t.strftime('%Y-%m-%d %H:%M'))

	message = '{}\n{}\n\n'.format(UTC_time_text,Local_time_text)
	message+= '\n'.join(table[2:])
	# message = message.replace('     ',' ')
	# message = message.replace('   ',' ')
	# message = message.replace('  ',' ')
	message = message.replace(' deg.','')

	v_text=''
	for i,row in volcs.sort_values('distance')[:3].iterrows():
		v_text='{}{} ({:.0f} km), '.format(v_text,row.Volcano,row.distance)
	v_text=v_text.replace('_',' ')
	message = '{}\n\nNearest volcanoes: {}\n'.format(message,v_text[:-2])
	message+= '\n{}'.format(os.environ['SACS_URL'])

	return subject, message