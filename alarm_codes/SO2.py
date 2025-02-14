from . import utils
import requests
from bs4 import BeautifulSoup
import pandas as pd
from obspy import UTCDateTime
import os
from PIL import Image
from urllib.parse import urlparse, urljoin
import matplotlib as m
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import traceback
import re

def run_alarm(config, T0, test=False):
	
	print('Reading SACS SO2 webpage')
	attempt = 1
	max_tries = 3
	while attempt <= max_tries:
		try:
			page = requests.get(os.environ['SACS_URL'], verify=False, timeout=10)
			soup = BeautifulSoup(page.content, 'html.parser')
			table= soup.find_all('pre')[0]
			break
		except:
			if attempt == max_tries:
				print('Page error.')
				state = 'WARNING'
				state_message = '{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				utils.icinga2_state(config, state, state_message)
				return
			print('Page error on attempt number {:g}'.format(attempt))
			attempt += 1

	try:
		table = table.get_text().split('\n')
		table = table[1:-1]

		date   = table[1].split(':')[-1].replace(' ','')
		time   = table[2].split(' :')[-1].split('UTC')[0].replace(' ','')

		lat_str = table[4].split(':')[-1]
		lon_str = table[3].split(':')[-1]
		lat, lat_dir = re.findall(r'(\d+\.\d+)\s{1}(\S{1})', lat_str)[0]
		lon, lon_dir = re.findall(r'(\d+\.\d+)\s{1}(\S{1})', lon_str)[0]
		lat = float(lat)
		lon = float(lon)
		if lat_dir == 'S':
			lat = -lat
		if lon_dir == 'W':
			lon = -lon

		volcs = pd.read_excel(config.volc_file)
		volcs = volcs[volcs['SO2']=='Y']
		volcs = utils.volcano_distance(lon, lat, volcs)
		volcs = volcs.sort_values('distance')


		# lon    = float(table[3].split(':')[-1].split('deg')[0].replace(' ',''))
		# lat    = float(table[4].split(':')[-1].split('deg')[0].replace(' ',''))
		# SZA    = table[4].split(':')[-1].split('deg')[0].replace(' ','')
		# SO2max = table[5].split(':')[-1].split('DU')[0].replace(' ','')
		# S02ht  = table[6].split(':')[-1].split('km')[0].replace(' ','')
	except:
		print('Page error.')
		state = 'WARNING'
		state_message = '{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
		utils.icinga2_state(config, state, state_message)	
		return	


	new_time = time_check(date, time, config)

	if new_time and volcs.distance.min() < config.max_distance:
		print('....New detection....')
		
		print('Downloading image')
		try:
			get_so2_images(soup, config)
		except:
			print('Problem downloading images.')

		print('Trying to make figure attachment')
		try:
			attachment = plot_fig(config)
			print('Figure generated successfully')
		except:
			attachment = []
			print('Problem making figure. Continue anyway')
			b = traceback.format_exc()
			err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
			print(err_message)
			pass

		
		print('Drafting alert')
		subject, message = create_message(date,time, table, config,volcs)
		
		# print('Sending direct alert')
		# utils.send_alert(config.alarm_name, subject, message, attachment)
		
		print('Update timestamp to avoid resending same alert')
		update_timestamp(date, time, config)
		
		print('Posting to Mattermost')
		utils.post_mattermost(config, subject, message, filename=attachment)


		# delete the file you just sent
		if attachment:
			os.remove(attachment)

		state_message = '{} (UTC) SO2 detection!'.format(T0.strftime('%Y-%m-%d %H:%M'))
		state = 'CRITICAL'
	elif volcs.distance.min() < config.max_distance and not new_time:
		state_message = '{} (UTC) Old SO2 detection! [{}]'.format(T0.strftime('%Y-%m-%d %H:%M'),
																UTCDateTime(date + time).strftime('%Y-%m-%d %H:%M'))
		state = 'WARNING'
	else:
		state_message='{} (UTC) No new SO2 detections'.format(T0.strftime('%Y-%m-%d %H:%M'))
		state='OK'

	# send heartbeat status message to icinga
	utils.icinga2_state(config,state,state_message)




def time_check(date, time, config):
	t_current = UTCDateTime(date + time)
	t_file = open(r'{}'.format(config.outfile), 'r')
	t_last = UTCDateTime(t_file.read())
	t_file.close()
	return t_last != t_current



def get_so2_images(soup, config):
	base_url = '://'.join(urlparse(os.environ['SACS_URL'])[:2])
	imgs = soup.find_all('img')
	img_files = []
	for im in imgs:
		if '/alert' in im.get('src'):
			img_files.append(urljoin(base_url, im.get('src')))


	for i, image in enumerate(img_files[:2]):

		r = requests.get(image, verify=False, timeout=10)
		if r.status_code == 200:
			with open(config.img_file.replace('.png', str(i+1)+'.gif'), 'wb') as out:
				for bits in r.iter_content():
					out.write(bits)

		gif = config.img_file.replace('.png', str(i+1)+'.gif')
		img = Image.open(gif)
		img.save(gif.replace('gif', 'png'), 'png', optimize=True, quality=300)
		os.remove(gif)



def plot_fig(config):	
	m.use('Agg')


	plt.figure(figsize=(3,4.4))

	tmp_file1 = config.img_file.replace('.png', '1.png')
	tmp_file2 = config.img_file.replace('.png', '2.png')
	img1 = mpimg.imread(tmp_file1)
	img2 = mpimg.imread(tmp_file2)

	plt.subplot(2, 1, 1)
	plt.imshow(img1)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])

	plt.subplot(2, 1, 2)
	plt.imshow(img2)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])

	plt.tight_layout(pad=0.5)

	jpg_file = utils.save_file(plt, config, dpi=500)

	os.remove(tmp_file1)
	os.remove(tmp_file2)

	return jpg_file



def update_timestamp(date, time, config):
	t_file = open(r'{}'.format(config.outfile), 'w+')
	t_file.write(str(UTCDateTime(date + time)))
	t_file.close()



def create_message(date, time, table, config, volcs):

	subject = 'SO2 detection'

	t = pd.Timestamp(UTCDateTime(date + time).datetime, tz='UTC')
	t_local = t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'), t_local.tzname())
	UTC_time_text = '{} UTC'.format(t.strftime('%Y-%m-%d %H:%M'))

	message = '{}\n{}\n\n'.format(UTC_time_text, Local_time_text)
	message+= '\n'.join(table[2:])
	# message = message.replace('     ',' ')
	# message = message.replace('   ',' ')
	# message = message.replace('  ',' ')
	message = message.replace(' deg.','')

	v_text = ''
	for i,row in volcs.sort_values('distance')[:3].iterrows():
		v_text = '{}{} ({:.0f} km), '.format(v_text, row.Volcano, row.distance)
	v_text=v_text.replace('_', ' ')
	message = '{}\n\nNearest volcanoes: {}\n'.format(message, v_text[:-2])
	message+= '\n{}'.format(os.environ['SACS_URL'])

	return subject, message