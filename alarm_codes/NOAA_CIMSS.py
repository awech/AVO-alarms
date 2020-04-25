from . import utils
import os
import pandas as pd
import numpy as np
import requests
from obspy import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth
import warnings
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import re
import matplotlib as m
from mpl_toolkits.basemap import Basemap
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import matplotlib.image as mpimg
from textwrap import wrap

warnings.filterwarnings("ignore")


def run_alarm(config,T0):

	### get alerts from volcview api
	print('Reading in alerts from volcview api .json file')
	attempt=1
	max_tries=3
	while attempt<=max_tries:
		try:
			result = os.popen('curl -H \"username:{}\" -H \"password:{}\" -X GET {}'.format(
							   os.environ['API_USERNAME'],os.environ['API_PASSWORD'],os.environ['NOAA_CIMSS_URL'])
							 ).read()
			A=pd.read_json(result)
			break
		except:
			if attempt==max_tries:
				print('whoops')
				break
				state='WARNING'
				state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				# utils.icinga_state(config,state,state_message)
				return
			print('Error opening .json file. Trying again')
			attempt+=1
	#################################
	#################################


	volcs=pd.read_csv('alarm_aux_files/volcanoes_kml.txt',
		delimiter='\t',names=['Volcano','kml','Lon','Lat'])	

	print('Looping through alerts...')
	for i, alert in A.iterrows():
		
		DIST=np.array([])
		for lat,lon in zip(volcs.Lat.values,volcs.Lon.values):
			dist, azimuth, az2=gps2dist_azimuth(lat,lon,alert.lat_rc,alert.lon_rc)
			DIST=np.append(DIST,dist/1000.)
		
		if DIST.min()<config.max_distance:
			
			print('Found alert <{:g} km from volcanoes!'.format(config.max_distance))
			old_alerts=pd.read_csv(config.outfile,names=['ids']).ids.values
			if int(alert.alert_url.split('/')[-1]) in old_alerts:
				print('....just kidding! Old alert.')
				continue
			else:
				print('New Alert! Getting images and additional info from NOAA CIMSS webpage...')
				volcs['distance']=DIST
				
				attempt=1
				max_tries=3
				while attempt<=max_tries:
					try:
						soup=scrape_web(alert)
						break
					except:
						if attempt==max_tries:
							print('Error reading NOAA CIMSS page')
							continue
						attempt+=1


				instrument=get_instrument(soup)
				height_text=get_height_txt(soup)
				get_cimss_image(soup,alert)
				print('Done.')
				print('Trying to make figure attachment')
				attachment=plot_fig(alert,volcs,config)
				try:
					attachment=plot_fig(alert,volcs,config)
					print('Figure generated successfully')
				except:
					attachment=[]
					print('Problem making figure. Continue anyway')
					pass

				# update old alerts file so you don't keep sending same one
				print('Update list of known alerts to avoid resending...')
				old_alerts=np.append(old_alerts,alert.alert_url.split('/')[-1])
				G=pd.DataFrame(old_alerts)
				G.to_csv(config.outfile,index=False,header=False)

				# craft and send the message
				print('Crafting message...')
				subject, message = create_message(alert,instrument,height_text,volcs)

				print('Sending message...')
				utils.send_alert(config.alarm_name,subject,message,attachment)
				print('Posting to mattermost...')
				utils.post_mattermost(config,subject,message,filename=attachment)

				# delete the file you just sent
				if attachment:
					os.remove(attachment)


def create_message(alert,instrument,height_text,volcs):
	t=pd.Timestamp(alert.object_date_time,tz='UTC')
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'),t_local.tzname())

	message = '{} UTC\n{}\n\n{}'.format(t.strftime('%Y-%m-%d %H:%M'),Local_time_text,height_text)
	message = '{}\nPrimary Instrument: {}'.format(message,instrument)
	message = '{}\nLatitude: {:.3f}\nLongitude: {:.3f}\n'.format(message,alert.lat_rc,alert.lon_rc)

	v_text=''
	for i,row in volcs.sort_values('distance')[:3].iterrows():
		v_text='{}{} ({:.0f} km), '.format(v_text,row.Volcano,row.distance)
	v_text=v_text.replace('_',' ')

	message = '{}Method: {}\n'.format(message,alert.method)
	message = '{}Nearest volcanoes: {}\n\n'.format(message,v_text[:-2])
	message = '{}More info: {}\n'.format(message,alert.alert_url)

	if 'GCA' in alert.method:
		subject = 'URGENT! {} at: {}'.format(alert.method.split(' (')[0],v_text[:-2])
	else:
		subject = '{} at: {}'.format(alert.method,v_text[:-2])

	return subject, message


def scrape_web(alert):

	soup    = BeautifulSoup(requests.get(alert.alert_url).content)
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
	tbl=soup.find('div',{'class':'alert_box alert_report_summary'})
	rows=tbl.find_all('tr')
	row=[tr for tr in rows if 'Primary' in str(tr)]
	instrument=row[0].find('td').text

	return instrument

def get_height_txt(soup):

	height_txt=soup.find(text=re.compile('AMSL'))
	if height_txt:
		height_txt+=':  '+height_txt.find_all_next('td')[0].text

	return height_txt


def get_cimss_image(soup,alert):
	
	base_url='://'.join(urlparse(alert.alert_url)[:2])
	image_files=soup.find(class_="alert_images").find_all('img')
	for i,img in enumerate(image_files):
		img.get('src')
		im_url=urljoin(base_url,img.get('src'))
		r = requests.get(im_url)

		if r.status_code == 200:
			with open('alarm_aux_files/noaa_out'+str(i+1)+'.png', 'wb') as out:
				for bits in r.iter_content():
					out.write(bits)


def plot_fig(alert,volcs,config):	
	m.use('Agg')

	latlims=[alert.lat_rc-2,alert.lat_rc+2]
	lonlims=[alert.lon_rc-4,alert.lon_rc+4]
	m_map = Basemap(projection='tmerc',llcrnrlat=latlims[0],urcrnrlat=latlims[1],
								  llcrnrlon=lonlims[0],urcrnrlon=lonlims[1],lat_0=alert.lat_rc,lon_0=alert.lon_rc,
								  resolution='i',area_thresh=25.0)

	#Create figure
	plt.figure(figsize=(3,6.6))

	ax=plt.subplot(3,1,3)
	m_map.drawcoastlines()
	m_map.drawmapboundary(fill_color='gray')
	m_map.fillcontinents(color='black',lake_color='gray')
	m_map.plot(alert.lon_rc,alert.lat_rc,'yo',latlon=True,markeredgecolor='white',markersize=6,markeredgewidth=0.5)
	v=volcs.copy().sort_values('distance')
	m_map.plot(v.Lon.values[:10],v.Lat.values[:10],'^r',latlon=True,markeredgecolor='black',markersize=4,markeredgewidth=0.5)

	parallels=np.array([np.round(alert.lat_rc*10)/10.-0.8,np.round(alert.lat_rc*10)/10.+0.8])
	meridians=np.array([np.round(alert.lon_rc*10)/10.-1.5,np.round(alert.lon_rc*10)/10.+1.5])
	m_map.drawparallels(parallels,color='w',textcolor='k',linewidth=0.5,dashes=[1,4],labels=[True,False,False,True],fontsize=6)
	m_map.drawmeridians(meridians,color='w',textcolor='k',linewidth=0.5,dashes=[1,4],labels=[False,True,False,True],fontsize=6)

	m_map.ax = ax

    # Inset map.
	axin = inset_axes(m_map.ax, width="25%", height="25%", loc=1,borderpad=0.3)
	latlims=[50.0,58.0]
	lonlims=[-189.9,-145]

	inmap = Basemap(projection='eqdc',lat_1=latlims[0],lat_2=latlims[1],
					lat_0=alert.lat_rc,lon_0=alert.lon_rc,width=3500000,height=3000000,
					resolution='i',area_thresh=100.0)

	inmap.drawcountries(color='0.2',linewidth=0.5)
	inmap.fillcontinents(color='gray')
	inmap.drawmapboundary(color='white',fill_color='gray')
	inmap.fillcontinents(color='black',lake_color='gray')
	bx, by = inmap(m_map.boundarylons, m_map.boundarylats)
	xy = list(zip(bx, by))
	mapboundary = Polygon(xy, edgecolor='y', linewidth=1, fill=False)
	axin.add_patch(mapboundary)


	img1 = mpimg.imread('alarm_aux_files/noaa_out1.png')
	img2 = mpimg.imread('alarm_aux_files/noaa_out2.png')

	plt.subplot(3,1,1)
	plt.imshow(img1)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])
	title_str='{} UTC\n{}\nMethod: {}'.format(str(alert.object_date_time),alert.alert_header.capitalize(),alert.method)
	plt.title(title_str,fontsize=8)

	plt.subplot(3,1,2)
	plt.imshow(img2)
	plt.gca().set_xticks([])
	plt.gca().set_yticks([])

	plt.tight_layout(pad=0.5)

	jpg_file=utils.save_file(plt,config,dpi=500)

	return jpg_file