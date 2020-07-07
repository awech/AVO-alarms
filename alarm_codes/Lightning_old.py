# Lightning alarm based on WWLLN data
#
# Wech 2017-06-08

import os
from . import utils
from obspy import UTCDateTime
import numpy as np
import pandas as pd
from obspy.geodetics.base import gps2dist_azimuth

######## WWLLN configuration ########
kml_map_file='alarm_aux_files/volcanoes_kml.txt'
url_base = os.environ['WWLLN_URL']
#####################################

# main function called by alarm.py
def run_alarm(config,T0):
	# Download the stroke data from the kml files
	kmls, v_lats, v_lons = get_kml_name(config.volcanoes)
	# Parse the stroke data into a pandas DataFrame
	CAT = parse_data(kmls)

	if len(CAT)==0:
		print('****** No lightning detected ******')
		state='OK'
		state_message='{} (UTC) No new strokes detected'.format(T0.strftime('%Y-%m-%d %H:%M'),config.alarm_name)
		CAT=CAT[CAT['time']>(T0-config.duration).strftime('%Y%m%d %H%M%S.%f')]
		CAT.to_csv(config.outfile,float_format='%.4f',index=False,sep='\t',date_format='%Y%m%dT%H%M%S.%f')
	else:
		# determine which volcano is closest the most recent stroke
		CAT=CAT.sort_values(by='time')
		X=np.array([gps2dist_azimuth(v_lats[i],v_lons[i],CAT.iloc[-1].lats,CAT.iloc[-1].lons) for i,v in enumerate(v_lons)])
		volcano=config.volcanoes[X[:,0].argmin()]
		V_LAT=v_lats[X[:,0].argmin()]
		V_LON=v_lons[X[:,0].argmin()]

		# count how many in 2 rings in past hour
		n_ring1, n_ring2 = count_events(V_LAT,V_LON,CAT.lats.values,CAT.lons.values,config)
		# now check if there are any new strokes
		lats, lons, times = check_new_strokes(CAT,config,T0)
		if len(lats)==0:
			print('********** OLD DETECTION **********')
			state='WARNING'
			state_message='{} (UTC) {} Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),volcano)
			state_message='{} {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,n_ring1,n_ring2,config.duration/60.0)
		else:
			print('********** NEW DETECTION **********')
			dx=np.array([gps2dist_azimuth(V_LAT,V_LON,CAT.lats.values[i],CAT.lons.values[i]) for i,n in enumerate(lats)])[:,0]/1000.

			CAT=CAT[CAT['time']>(T0-config.duration).strftime('%Y%m%d %H%M%S.%f')]
			CAT.to_csv(config.outfile,float_format='%.4f',index=False,sep='\t',date_format='%Y%m%dT%H%M%S.%f')

			if dx[0]>config.dist1:
				print('********** DISTAL DETECTION 1st **********')
				state='WARNING'
				state_message='{} (UTC) {} Distal Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),volcano)
				state_message='{} {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,n_ring1,n_ring2,config.duration/60.0)
			else:
				print('********** PROXIMAL DETECTION 1st **********')
				state='CRITICAL'
				state_message='{} (UTC) {} Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),volcano)
				state_message='{} {} new strokes! {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,len(lats),n_ring1,n_ring2,config.duration/60.0)
				### Send Email Notification ####
				dist, azimuth, az2=gps2dist_azimuth(V_LAT,V_LON,lats.mean(),lons.mean())
				craft_and_send_email(config,volcano,dist,azimuth,times,CAT)
			
	utils.icinga_state(config,state,state_message)
	utils.icinga2_state(config,state,state_message)


def count_events(V_LAT,V_LON,lats,lons,config):
	X=np.array([gps2dist_azimuth(V_LAT,V_LON,lats[i],lons[i]) for i,n in enumerate(lats)])
	X=X[:,0]/1000.0
	n_ring1=len(X[X<config.dist1])
	Y=X[X>config.dist1]
	n_ring2=len(Y[Y<config.dist2])

	return n_ring1, n_ring2

def check_new_strokes(CAT,config,T0):

	L=pd.read_csv(config.outfile,delimiter='\t',parse_dates=['time'])
	L=L.append(CAT)
	L=L.drop_duplicates(keep=False)
	L=L[L['time']>(T0-3600).strftime('%Y%m%d %H%M%S.%f')]


	lats=L.lats.values.astype('float')
	lons=L.lons.values.astype('float')
	times=L.time.values

	return lats, lons, times

def get_kml_name(volcanoes):
	V=pd.read_csv(kml_map_file,delim_whitespace=True,names=['Volcano','kml','lon','lat'])
	kmls=[V[V['Volcano']==v].kml.tolist()[0] for v in volcanoes]
	v_lats=np.array([V[V['Volcano']==v].lat.tolist()[0] for v in volcanoes])
	v_lons=np.array([V[V['Volcano']==v].lon.tolist()[0] for v in volcanoes])

	return kmls, v_lats, v_lons

def parse_data(kmls):
	from urllib.request import urlopen
	import re
	
	lats=list()
	lons=list()
	time=list()

	for kml in kmls:
		data=[]
		for i in range(3):
			try:
				data=urlopen(url_base+kml,timeout=4).read()
				break
			except:
				continue

		lats += re.findall('<li>Lat: ([^<]*)</li>',str(data))
		lons += re.findall('<li>Lon: ([^<]*)</li>',str(data))
		time += re.findall('<name>(\d[^<]*)</name>',str(data))


	lats=np.array(lats).astype('float')
	lons=np.array(lons).astype('float')
	time=pd.to_datetime([t.replace('60Z','59.99Z') for t in time])
	CAT=pd.DataFrame({'time':time,'lats':lats,'lons':lons})
	CAT=CAT.drop_duplicates()

	return CAT

def craft_and_send_email(config,volcano,dist,azimuth,times,CAT):
	# create the subject line
	subject='--- {} Lightning ---'.format(volcano)

	# create the test for the message you want to send
	message='\n{} new strokes! ({} total)'.format(len(times),len(CAT))
	message='{}\n{:.0f} km from {}'.format(message,dist/1000.0,volcano)
	message='{}\nAzimuth: {:.0f} degrees'.format(message,azimuth)
	message='{}\n\nMost recent:'.format(message)
	t=pd.Timestamp(times[-1],tz='UTC')
	message='{}\n{} (UTC)'.format(message,t.strftime('%Y-%m-%d %H:%M:%S'))
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	message='{}\n{} ({})'.format(message,t_local.strftime('%Y-%m-%d %H:%M:%S'),t_local.tzname())

	utils.send_alert(config.alarm_name,subject,message,filename=None)
	utils.post_mattermost(config,subject,message,filename=None)
