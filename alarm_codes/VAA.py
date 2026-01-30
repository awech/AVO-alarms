from . import utils
import os
import re
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from obspy.geodetics.base import gps2dist_azimuth
from obspy import UTCDateTime
import cartopy
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import matplotlib.pyplot as plt
import matplotlib as m
from matplotlib.path import Path
import traceback
import warnings
warnings.filterwarnings("ignore")



def run_alarm(config,T0):

	print(T0)
	attempt = 1
	max_tries = 3
	while attempt <= max_tries:
		try:
			tables = read_urls()
			break
		except:		
			if attempt == max_tries:
				print('Whoops.')
				state='WARNING'
				state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				utils.icinga2_state(config,state,state_message)
				return
			print('Page error on attempt number {:g}'.format(attempt))
			attempt += 1						

	try:
		VAAS_FOUND = []
		for t in tables:
			if 'VAAC: ANCHORAGE' in t.contents[0]:
				if 'weather.gov' in os.environ['VAA_URL']:
					evt = process_vaa(t.getText().split('\n\n')) # if using NWS site
				else:
					evt = process_vaa(t.getText().split('\r\n\r\n')) # if using discovery news site
				if UTCDateTime(evt['DTG']) > T0 - config.duration:
					VAAS_FOUND.append(evt)
	except:
		print('Page error.')
		state='WARNING'
		state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
		utils.icinga2_state(config,state,state_message)	
		return	


	if len(VAAS_FOUND)==0:
		state='OK'
		state_message='{} (UTC) No new VAAs'.format(T0.strftime('%Y-%m-%d %H:%M'))
		utils.icinga2_state(config,state,state_message)	
		return


	OLD_VAAS = pd.read_csv(config.outfile)
	VAAS_FOUND.reverse()

	for evt in VAAS_FOUND:

		if evt['VAA_ID'] in OLD_VAAS.ID.to_list():
			print('Old VAA detected')
			state='WARNING'
			state_message='{} (UTC) Old VAA detected'.format(T0.strftime('%Y-%m-%d %H:%M'))
			utils.icinga2_state(config,state,state_message)	
			continue

		else:
			print('New VAA detected')

			OLD_VAAS = pd.concat([OLD_VAAS, pd.DataFrame({'ID':[evt['VAA_ID']]})], ignore_index=True)
			OLD_VAAS.to_csv(config.outfile, index=False)

			lons_0, lats_0, level, time, direction = process_polygons(evt, 'OBS VA CLD')
			lons_6, lats_6, level, time, direction = process_polygons(evt, 'FCST VA CLD +6HR')
			lons_12, lats_12, level, time, direction = process_polygons(evt, 'FCST VA CLD +12HR')
			lons_18, lats_18, level, time, direction = process_polygons(evt, 'FCST VA CLD +18HR')

			LONS = np.concatenate((lons_0, lons_6, lons_12, lons_18))
			LATS = np.concatenate((lats_0, lats_6, lats_12, lats_18))

			if len(LONS)>1:
				#### Generate Figure ####
				try:
					attachment = make_map(evt, LONS, LATS, config)
				except:
					attachment = []
					print('Problem making figure. Continue anyway')
					b = traceback.format_exc()
					err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
					print(err_message)
			else:
				attachment = []
				
			subject, message = create_message(evt)
			# print('Sending message...')
			# utils.send_alert(config.alarm_name, subject, message, attachment)
			print('Posting to mattermost...')
			utils.post_mattermost(config, subject, message, filename=attachment)

			# delete the file you just sent
			if attachment:
				os.remove(attachment)

			state = 'CRITICAL'
			state_message = f'{T0.strftime("%Y-%m-%d %H:%M")} (UTC) New {subject}'
			
			utils.icinga2_state(config, state, state_message)


def read_urls():

	if 'weather.gov' in os.environ['VAA_URL']:
		page = requests.get(os.environ['VAA_URL'], timeout=10, verify=False) # if using NWS site
		page2 = requests.get(os.environ['VAA_URL'].replace('ak1','ak2'), timeout=10, verify=False) # if using NWS site
		page3 = requests.get(os.environ['VAA_URL'].replace('ak1','ak3'), timeout=10, verify=False) # if using NWS site
		page4 = requests.get(os.environ['VAA_URL'].replace('ak1','ak4'), timeout=10, verify=False) # if using NWS site
		page5 = requests.get(os.environ['VAA_URL'].replace('ak1','ak5'), timeout=10, verify=False) # if using NWS site

		soup  = BeautifulSoup(page.content, 'html.parser')
		soup2 = BeautifulSoup(page2.content, 'html.parser')
		soup3 = BeautifulSoup(page3.content, 'html.parser')
		soup4 = BeautifulSoup(page4.content, 'html.parser')
		soup5 = BeautifulSoup(page5.content, 'html.parser')

		soup.append(soup2)
		soup.append(soup3)
		soup.append(soup4)
		soup.append(soup5)
	else:
		page = requests.get(os.environ['VAA_URL'], timeout=10) # if using discovery news site
		soup = BeautifulSoup(page.content, 'html.parser')

	tables = soup.find_all('pre')

	return tables


def get_extent(LONS, LATS):

	lat0 = np.mean([LATS.max(), LATS.min()])
	lon0 = np.mean([LONS.max(), LONS.min()])
	lat_dist = gps2dist_azimuth(LATS.min(), lon0, LATS.max(), lon0)[0] / 1000
	lon_dist = gps2dist_azimuth(lat0, LONS.min(), lat0, LONS.max())[0] / 1000

	dist = np.max([lat_dist, lon_dist])
	dist = np.round(1.5 * dist)

	dlat = dist / 111.1
	dlon = dlat / np.cos(lat0 * np.pi / 180)

	latmin = lat0 - dlat/2
	latmax = lat0 + dlat/2
	lonmin = lon0 - dlon/2
	lonmax = lon0 + dlon/2

	return [lonmin, lonmax, latmin, latmax]


def make_path(extent):
	n = 20
	aoi = Path(
	    list(zip(np.linspace(extent[0],extent[1], n), np.full(n, extent[3]))) + \
	    list(zip(np.full(n, extent[1]), np.linspace(extent[3], extent[2], n))) + \
	    list(zip(np.linspace(extent[1], extent[0], n), np.full(n, extent[2]))) + \
	    list(zip(np.full(n, extent[0]), np.linspace(extent[2], extent[3], n)))
	)

	return(aoi)


def process_polygons(evt, field):
	lats = []
	lons = []
	level = ''
	time = ''
	direction = ''

	if field not in evt.keys():
		return lons, lats, level, time, direction

	obs_text = evt[field].replace('\r\n', ' ')

	if 'VA NOT IDENTIFIABLE ' in obs_text:
		return lons, lats, level, time, direction

	if 'FL' in obs_text:

		time_pattern = re.compile(r'\S+/\S+Z')
		lvl_pattern = re.compile(r'\S+/FL\S+')
		move_pattern = re.compile(r'MOV.+')

		level = lvl_pattern.findall(obs_text)
		time = time_pattern.findall(obs_text)
		direction = move_pattern.findall(obs_text)
		if level:
			level = level[0]
		else:
			level = ''
		if time:
			time = time[0]
		else:
			time = ''
		if direction:
			direction = direction[0]
		else:
			direction = ''

		tmp_text = obs_text.replace(level, '')
		tmp_text = tmp_text.replace(time, '')
		tmp_text = tmp_text.replace(direction, '')
		lat_lon_txt_pairs = tmp_text.split(' - ')

		for pr in lat_lon_txt_pairs:
			tmp_lat, tmp_lon = text_to_latlon(pr)
			lats.append(tmp_lat)
			lons.append(tmp_lon)

	return lons, lats, level, time, direction


def text_to_latlon(latlon_txt):
	pr = latlon_txt.strip()
	pr = pr.replace('E','')
	pr = pr.replace('W','-')
	pr = pr.replace('N','')
	pr = pr.replace('S','-')
	pr = pr.split(' ')

	tmp_lat = pr[0]
	tmp_lon = pr[1]

	lat_sign =  np.sign(float(tmp_lat))
	lon_sign =  np.sign(float(tmp_lon))

	tmp_lat = float(tmp_lat[:-2]) + lat_sign*float(tmp_lat[-2:])/60
	tmp_lon = float(tmp_lon[:-2]) + lon_sign*float(tmp_lon[-2:])/60

	if tmp_lon > 0:
		tmp_lon -= 360

	return tmp_lat, tmp_lon


def process_vaa(evt):
	vaa = dict()

	if 'weather.gov' in os.environ['VAA_URL']:
		vaa['header'] = evt[0].replace('\n', ' ') # if using NWS site
	else:
		vaa['header'] = evt[0] # if using discovery news site
	rows = ['DTG',
			'VAAC',
			'VOLCANO',
			'PSN',
			'AREA',
			'SUMMIT ELEV',
			'ADVISORY NR',
			'INFO SOURCE',
			'AVIATION COLOR CODE',
			'ERUPTION DETAILS',
			'OBS VA DTG',
			'OBS VA CLD',
			'FCST VA CLD +6HR',
			'FCST VA CLD +12HR',
			'FCST VA CLD +18HR',
			'RMK',
			'NXT ADVISORY']
	for row in rows:
		if 'weather.gov' in os.environ['VAA_URL']:
			for line in evt:
				if row+':' in line and not 'VA ' + row+':' in line:
					vaa[row] = line.split(': ')[-1].replace('\n', ' ') # for NWS site
		else:
			vaa[row] = [line for line in evt if row+':' in line][0].split(': ')[-1] # volcano discovery site
		
	vaa['VAA_ID']='{}_{}'.format(vaa['DTG'], vaa['VOLCANO'].split(' ')[0])
	return vaa


def make_map(evt, LONS, LATS, config):

	m.use('Agg')
	v_lat, v_lon = text_to_latlon(evt['PSN'])
	LONS = np.append(LONS, v_lon)
	LATS = np.append(LATS, v_lat)
	extent = get_extent(LONS, LATS)

	fig = plt.figure(figsize=(4,4))

	CRS2 = cartopy.crs.AlbersEqualArea(central_longitude=np.mean(extent[:2]), central_latitude=np.mean(extent[2:]), globe=None)
	ax1 = plt.subplot(111, projection=CRS2)
	ax1.set_boundary(make_path(extent), transform=cartopy.crs.Geodetic())
	ax1.set_extent(extent, cartopy.crs.Geodetic())
	coast = cartopy.feature.GSHHSFeature(scale="intermediate", rasterized=True)
	ax1.add_feature(coast, facecolor="lightgray", linewidth=0.2)
	ax1.set_facecolor('powderblue')

	lon_grid = [np.mean(extent[:2])-np.diff(extent[:2])[0]/4, np.mean(extent[:2])+np.diff(extent[:2])[0]/4]
	lat_grid = [np.mean(extent[-2:])-np.diff(extent[-2:])[0]/4, np.mean(extent[-2:])+np.diff(extent[-2:])[0]/4]

	gl = ax1.gridlines(draw_labels=True, xlocs=lon_grid, ylocs=lat_grid,
					   alpha=0.5, 
					   color='k',
					   linestyle='--', 
					   linewidth=0.5)

	gl.xlabels_top = False
	gl.ylabels_left = False
	gl.xformatter = LONGITUDE_FORMATTER
	gl.yformatter = LATITUDE_FORMATTER
	gl.xlabel_style = {'size': 6}
	gl.ylabel_style = {'size': 6}

	lons_0, lats_0, level, time, direction = process_polygons(evt, 'OBS VA CLD')
	lons_6, lats_6, level, time, direction = process_polygons(evt, 'FCST VA CLD +6HR')
	lons_12, lats_12, level, time, direction = process_polygons(evt, 'FCST VA CLD +12HR')
	lons_18, lats_18, level, time, direction = process_polygons(evt, 'FCST VA CLD +18HR')

	if lons_0:
		ax1.plot(lons_0, lats_0, '-', color='firebrick', linewidth=2, label='Observed', transform=cartopy.crs.Geodetic(), zorder=100)
	if lons_6:
		ax1.plot(lons_6, lats_6, '--', color='orangered', linewidth=1.5, label='6H Forecast', transform=cartopy.crs.Geodetic(), zorder=99)
	if lons_12:
		ax1.plot(lons_12, lats_12, '--', color='orange', linewidth=1.25, label='12H Forecast', transform=cartopy.crs.Geodetic(), zorder=98)
	if lons_18:
		ax1.plot(lons_18, lats_18, '-.', color='goldenrod', linewidth=1.0, label='18H Forecast', transform=cartopy.crs.Geodetic(), zorder=97)

	ax1.plot(v_lon, v_lat, 'w^', markerfacecolor='k', markersize=8, transform=cartopy.crs.PlateCarree())

	ax1.legend(fontsize=6, loc='lower left')

	volcano_name = ''.join(evt['VOLCANO'].split(' ')[:-1]).title()
	vaa_time = UTCDateTime(evt['DTG']).strftime('%Y-%m-%d %H:%M')

	lvl_pattern = re.compile(r'/FL\S+')
	vaa_height = 100*float(lvl_pattern.findall(evt['OBS VA CLD'])[0].split('FL')[-1])
	# ax1.set_title('{} VAA to {:,} ft\n{}'.format(, )
	ax1.set_title(f'{volcano_name} VAA to {vaa_height:,.0f} ft \n{vaa_time}', fontsize=10)
	plt.tight_layout()

	print('Saving figure...')
	jpg_file = utils.save_file(fig, config, dpi=250)
	plt.close(fig)

	return jpg_file


def create_message(evt):

	volcano_name = ''.join(evt['VOLCANO'].split(' ')[:-1]).title()
	subject = f'{volcano_name} Volcanic Ash Advisory'

	t=pd.Timestamp(UTCDateTime(evt['DTG']).datetime,tz='UTC')
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'),t_local.tzname())
	UTC_time_text = '{} UTC'.format(t.strftime('%Y-%m-%d %H:%M'))

	try:
		lvl_pattern = re.compile(r'/FL\S+')
		vaa_height = 100*float(lvl_pattern.findall(evt['OBS VA CLD'])[0].split('FL')[-1])
		message = f'VAA to {vaa_height:,.0f} ft\n{UTC_time_text}\n{Local_time_text}\n\n#### *Original Message*\n'
	except:
		message = f'Volcanic Ash Advisory\n{UTC_time_text}\n{Local_time_text}\n\n#### *Original Message*\n'
	
	for key in evt.keys():
		if key not in ['header', 'VAA_ID']:
			message+=f'**{key}:** {evt[key]}\n'

	message = message.replace('\r\n', ' ')

	return subject, message

