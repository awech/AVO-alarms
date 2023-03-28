from . import utils
import os
import pandas as pd
import numpy as np
import requests
from obspy.geodetics.base import gps2dist_azimuth
import warnings
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re
import matplotlib as m
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import matplotlib.image as mpimg
import traceback


warnings.filterwarnings("ignore")


def run_alarm(config, T0):

	### get alerts from volcview api ###
	####################################
	print('Reading in alerts from volcview api .json file')
	attempt = 1
	max_tries = 3
	while attempt <= max_tries:
		try:
			result = os.popen('curl -H \"username:{}\" -H \"password:{}\" -X GET {}'.format(
							   os.environ['API_USERNAME'], os.environ['API_PASSWORD'],
							   os.environ['NOAA_CIMSS_URL'])
							 ).read()
			A = pd.read_json(result)
			break
		except:
			if attempt == max_tries:
				print('whoops')
				state = 'WARNING'
				state_message = '{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				utils.icinga_state( config, state, state_message)
				utils.icinga2_state(config, state, state_message)
				return
			print('Error opening .json file. Trying again')
			attempt+=1
	
	if 'A' not in locals():
		state = 'WARNING'
		state_message = '{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
		utils.icinga_state( config, state, state_message)
		utils.icinga2_state(config, state, state_message)
		return
	####################################
	####################################


	####################################
	####################################
	# volcs = pd.read_csv('alarm_aux_files/volcanoes_kml.txt',
	# 				  delimiter='\t',
	# 				  names=['Volcano','kml','Lon','Lat'])
	VOLCS = pd.read_excel(config.volc_file)

	# update DataFrame with unique NOAA/CIMSS id
	A['NOAA_id'] = ''
	for i in A.index:
		try:
			A.at[i, 'NOAA_id'] = int(A.at[i,'alert_url'].split('/')[-1])
		except:
			A.at[i, 'NOAA_id'] = 0 	# alert has no url to scrap info from
	A = A[A['NOAA_id'] > 0] 		# ignore alerts with no urls

	
	A['object_date_time'] = pd.to_datetime(A['object_date_time']) 						# convert time to datetime in DataFrame
	recent_alerts = A[A['object_date_time'] > (T0-3600*12).strftime('%Y-%m-%d %H:%M')]	# limit DataFrame to alerts in the past 12 hours
	old_alerts = pd.read_csv(config.outfile)											# read in old alerts

	# now update alerts file
	A[['object_date_time','NOAA_id','vv_id']].to_csv(config.outfile, index=False)

	if len(recent_alerts) == 0:
		state = 'WARNING'
		state_message = '{} (UTC) No new recent NOAA CIMSS alerts. Webpage or API problem?'.format(T0.strftime('%Y-%m-%d %H:%M'))


	print('Looping through alerts...')
	for i, alert in recent_alerts.iterrows():
		
		# DIST = np.array([])
		# for lat, lon in zip(volcs.Lat.values, volcs.Lon.values):
		# 	dist, azimuth, az2 = gps2dist_azimuth(lat, lon, alert.lat_rc, alert.lon_rc)
		# 	DIST = np.append(DIST, dist/1000.)
		# volcs['distance'] = DIST
		# volcs = volcs.sort_values('distance')
		
		# keep only those volcanoes based on NOAA alert type
		ALERT_TYPE = {'ash': 'NOAA Ash', 'hot': 'NOAA Thermal', 'ice': 'NOAA Ice'}
		volcs = VOLCS[VOLCS[ ALERT_TYPE[alert.alert_type] ] =='Y']

		volcs = utils.volcano_distance(alert.lon_rc, alert.lat_rc, volcs)
		volcs = volcs.sort_values('distance')

		if volcs.distance.min() >= config.max_distance:
			state = 'OK'
			state_message = '{} (UTC) No new NOAA CIMSS alerts'.format(T0.strftime('%Y-%m-%d %H:%M'))
		
		else:
			
			print('Found alert <{:g} km from volcanoes.'.format(config.max_distance))
			if alert.NOAA_id in old_alerts.NOAA_id.values:
				print('....just kidding! Old alert.')
				state = 'OK'
				state_message = '{} (UTC) No new NOAA CIMSS alerts'.format(T0.strftime('%Y-%m-%d %H:%M'))
				continue
			else:
				print('New Alert! Getting images and additional info from NOAA CIMSS webpage...')
				print(alert)
							
				attempt = 1
				max_tries = 3
				while attempt <= max_tries:
					try:
						soup = scrape_web(alert)
						break
					except:
						if attempt == max_tries:
							print('Error reading NOAA CIMSS page')
							state = 'WARNING'
							state_message = '{} (UTC) NOAA/CIMSS webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
							continue
						

				instrument = get_instrument(soup)
				height_text = get_height_txt(soup)
				get_cimss_image(soup, alert, config)
				print('Done.')


				print('Trying to make figure attachment')
				try:
					attachment = plot_fig(alert, volcs, config)
					print('Figure generated successfully')
				except:
					attachment = []
					print('Problem making figure. Continue anyway')
					b = traceback.format_exc()
					err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
					print(err_message)
					pass

				# craft and send the message
				print('Crafting message...')
				subject, message = create_message(alert, instrument, height_text, volcs)

				print('Sending message...')
				utils.send_alert(config.alarm_name, subject, message, attachment)
				print('Posting to mattermost...')
				utils.post_mattermost(config, subject, message, filename=attachment)


				##################################################################
				# Send thermal alerts to their own channel
				#
				if alert.alert_type == 'hot':
					if volcs.iloc[0].distance < config.thermal_alert_dist:
						config.mattermost_channel_id = config.thermal_alerts_mm
						utils.post_mattermost(config, subject, message, filename=attachment)
				#
				##################################################################


				##################################################################
				# Send alerts for elevated volcanoes to their own channel
				#
				elevated_volcs = volcs[volcs['Volcano'].isin(config.elevated_volcano_list)]

				if elevated_volcs.iloc[0].distance < config.elevated_volcano_dist:
					subject_elevate, message_ignore = create_message(alert, instrument, height_text, elevated_volcs)
					config.mattermost_channel_id = config.elevated_volcano_mm
					utils.post_mattermost(config, subject_elevate, message, filename=attachment)
				#
				##################################################################

				state = 'CRITICAL'
				state_message = '{} (UTC) {}'.format(T0.strftime('%Y-%m-%d %H:%M'), subject)

				# delete the file you just sent
				if attachment:
					os.remove(attachment)

	utils.icinga_state( config, state, state_message)
	utils.icinga2_state(config, state, state_message)


def create_message(alert, instrument, height_text, volcs):
	t = pd.Timestamp(alert.object_date_time, tz='UTC')
	t_local = t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'), t_local.tzname())

	message = '{} UTC\n{}\n\n{}'.format(t.strftime('%Y-%m-%d %H:%M'), Local_time_text, height_text)
	message = '{}\nPrimary Instrument: {}'.format(message, instrument)
	message = '{}\nLatitude: {:.3f}\nLongitude: {:.3f}\n'.format(message, alert.lat_rc, alert.lon_rc)

	volcs = volcs.sort_values('distance')
	v_text = ''
	for i, row in volcs[:3].iterrows():
		v_text = '{}{} ({:.0f} km), '.format(v_text, row.Volcano, row.distance)
	v_text = v_text.replace('_',' ')

	message = '{}Method: {}\n'.format(message, alert.method)
	message = '{}Nearest volcanoes: {}\n\n'.format(message, v_text[:-2])
	message = '{}More info: {}\n'.format(message, alert.alert_url)

	subject_text = alert.alert_header.title().replace(' Found','')
	subject_text = subject_text.replace(' Detected','')
	subject = '{}: {}'.format(volcs.iloc[0].Volcano, subject_text)

	return subject, message


def scrape_web(alert):

	soup = BeautifulSoup(requests.get(alert.alert_url).content)
	redir = soup.select_one("#loginform-custom")["action"]

	#This URL will be the URL that your login form points to with the "action" tag.
	POST_LOGIN_URL = redir
	#This URL is the page you actually want to pull down with requests.
	REQUEST_URL = alert.alert_url

	payload = {
	    'log': os.environ['CIMSS_USERNAME'],
	    'pwd': os.environ['CIMSS_PASSWORD']
	}

	with requests.Session() as session:
		post = session.post(POST_LOGIN_URL, data=payload)
		r    = session.get(REQUEST_URL)
		soup = BeautifulSoup(r.content)
	session.close()

	return soup


def get_instrument(soup):
	tbl = soup.find('div', {'class':'alert_box alert_report_summary'})
	rows = tbl.find_all('tr')
	row = [tr for tr in rows if 'Primary' in str(tr)]
	instrument = row[0].find('td').text

	return instrument

def get_height_txt(soup):

	height_txt = soup.find(text=re.compile('AMSL'))
	if height_txt:
		height_txt += ':  '+height_txt.find_all_next('td')[0].text

	return height_txt


def get_cimss_image(soup,alert,config):
	
	base_url = '://'.join(urlparse(alert.alert_url)[:2])
	image_files = soup.find(class_="alert_images").find_all('img')
	for i, img in enumerate(image_files):
		img.get('src')
		im_url = urljoin(base_url, img.get('src'))
		r = requests.get(im_url)

		if r.status_code == 200:
			with open(config.img_file.replace('.png',str(i+1)+'.png'), 'wb') as out:
				for bits in r.iter_content():
					out.write(bits)


def plot_fig(alert, volcs, config):	
	m.use('Agg')

	#Create figure
	plt.figure(figsize=(3, 6.6))	
	ax = plt.subplot(3, 1, 3)

	lat0 = alert.lat_rc
	lon0 = alert.lon_rc
	m_map, inmap = utils.make_map(ax, lat0, lon0, main_dist=150, inset_dist=400, scale=50)

	m_map.plot(lat0, lon0, 
			   'o', 
			   latlon=True, 
			   markeredgecolor='black', 
			   markerfacecolor='gold', 
			   markersize=6, 
			   markeredgewidth=0.5)

	v = volcs.copy().sort_values('distance')
	m_map.plot(v.Longitude.values[:10], v.Latitude.values[:10],
			   '^',
			   latlon=True,
			   markerfacecolor='forestgreen',
			   markeredgecolor='black',
			   markersize=4,
			   markeredgewidth=0.5)

	# draw rectangle on inset map
	bx, by = inmap(m_map.boundarylons, m_map.boundarylats)
	xy = list(zip(bx, by))
	mapboundary = Polygon(xy, edgecolor='firebrick', linewidth=0.5, fill=False)
	inmap.ax.add_patch(mapboundary)

	# read in images downloaded from NOAA/CIMSS webpage
	tmp_file1 = config.img_file.replace('.png', '1.png')
	tmp_file2 = config.img_file.replace('.png', '2.png')
	img1 = mpimg.imread(tmp_file1)
	img2 = mpimg.imread(tmp_file2)

	plt.subplot(3, 1, 1)
	plt.imshow(img1)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])
	title_str = '{} UTC\n{}\nMethod: {}'.format(str(alert.object_date_time), alert.alert_header.capitalize(), alert.method)
	plt.title(title_str, fontsize=8)

	plt.subplot(3,1,2)
	plt.imshow(img2)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])

	plt.tight_layout(pad=0.5)

	jpg_file = utils.save_file(plt, config, dpi=500)

	# remove images downloaded from NOAA/CIMSS webpage
	os.remove(tmp_file1)
	os.remove(tmp_file2)

	return jpg_file
