# Lightning alarm based on WWLLN & Earth Networks data
#
# Wech 2020-04-09

import os
import json
import numpy as np
import pandas as pd
from obspy import UTCDateTime
from obspy.geodetics.base import gps2dist_azimuth
import utils
import warnings
warnings.filterwarnings("ignore")


def run_alarm(config,T0):

	### get alerts from volcview api
	print('Reading in alerts from volcview api .json file')
	attempt=1
	max_tries=3
	while attempt<=max_tries:
		try:
			data = json.load(os.popen('curl -H \"username:{}\" -H \"password:{}\" -X GET {}'.format(
											os.environ['API_USERNAME'],os.environ['API_PASSWORD'],os.environ['LIGHTNING_URL'])))
			A=pd.DataFrame(data['lightning'])
			break
		except:
			if attempt==max_tries:
				print('whoops')
				break
				state='WARNING'
				state_message='{} (UTC) webpage error'.format(T0.strftime('%Y-%m-%d %H:%M'))
				# utils.icinga_state(config.alarm_name,state,state_message)
				return
			print('Error opening .json file. Trying again')
			attempt+=1
	#################################
	#################################

	if len(A)>0:
		A_recent, A_new = get_new_strokes(A,T0,config)
		volcanoes=A_new.volcanoName.unique()
	else:
		volcanoes=[]
		A_recent=make_blank_df()

	if len(volcanoes)==0:
		print('****** No lightning detected ******')
		state='OK'
		state_message='{} (UTC) {} normal'.format(T0.strftime('%Y-%m-%d %H:%M'),config.alarm_name)
		A_recent.to_csv(config.outfile,index=False)
	
	else:
		print('Lightning detected at {:.0f} volcanoe(s)'.format(len(volcanoes)))
		for v in volcanoes:
			if not v:
				print('Null volcano. Skipping...')
				continue
			print('--- Processing detects at {} volcano ---'.format(v))

			V_new = A_new[A_new['volcanoName']==v]
			V_recent = get_distances2(A_recent,V_new.iloc[0].volcanoLatitude,V_new.iloc[0].volcanoLongitude)
			V_recent = V_recent[V_recent['latest_distance']<config.dist2]
			
			
			# check if changing volcanoes means no events < dist2 ???????
			# ????????
			if len(V_recent)==0:
				continue
			

			V_recent = sort_by_time(V_recent)
			n_ring1, n_ring2 = inner_outer(V_recent.latest_distance,config)
		
			if len(A_new)==0:
				print('********** OLD DETECTION **********')
				state='WARNING'
				state_message='{} (UTC) {} Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),V_recent.iloc[0].volcanoName)
				state_message='{} {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,n_ring1,n_ring2,config.duration/60.0)
				A_recent.to_csv(config.outfile,index=False)

			else:
				print('********** NEW DETECTION **********')
				A_recent.to_csv(config.outfile,index=False)
			
				if V_recent.iloc[-1].latest_distance>config.dist1:
					print('********** DISTAL DETECTION 1st **********')
					state='WARNING'
					state_message='{} (UTC) {} Distal Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),V_recent.iloc[0].volcanoName)
					state_message='{} {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,n_ring1,n_ring2,config.duration/60.0)
			
				else:
					print('********** PROXIMAL DETECTION 1st **********')
					state='CRITICAL'
					state_message='{} (UTC) {} Lightning Detection!'.format(T0.strftime('%Y-%m-%d %H:%M'),V_recent.iloc[0].volcanoName)
					state_message='{} {} new strokes! {} strokes < 20 km (20 km < {} < 100 km) in past {:.0f} minutes.'.format(state_message,len(A_new),n_ring1,n_ring2,config.duration/60.0)
					
					### Send Email Notification ####
					print('Crafting message...')
					subject, message = create_message(V_recent,V_new,config)
					try:
						attachment = plot_fig(V_recent, config, T0)
					except:
						attachment = None
					
					print('Sending message...')
					utils.send_alert(config.alarm_name,subject,message,filename=attachment)
					print('Posting message to Mattermost...')
					utils.post_mattermost(config.alarm_name,subject,message,filename=attachment)
					if attachment:
						os.remove(attachment)
		

		# utils.icinga_state(config.alarm_name,state,state_message)


def make_blank_df():
	columns=['dataSource',
			 'lightningId',
			 'lightningLatitude',
			 'lightningLongitude',
			 'lightningTimestamp',
			 'nearestDistanceKm',
			 'volcanoLatitude',
			 'volcanoLongitude',
			 'volcanoName',
			 'datetime']
	df=pd.DataFrame([],columns=columns)

	for c in df.columns:
		if c in ['dataSource','volcanoName','datetime']:
			continue
		df[c]=pd.to_numeric(df[c])
	
	return df


def get_new_strokes(A,T0,config):

	# clean up the dataframe, removing excess columns
	A_recent=A.drop( ['volcanoElevationM', 
				'nearestVnum', 
				'peakCurrent', 
				'residual',
				'stationTotal', 
				'usgsDelaySeconds', 
				'usgsInsertDate',
				'usgsTimestamp', 
				'flashType', 
				'icHeight',
				'icMultiplicity', 
				'isAvoInd', 
				'lightningDate', 
				'cgMultiplicity'],
				axis=1)

	# convert strings to numbers
	for c in A_recent.columns:
		if c in ['dataSource','volcanoName','datetime']:
			continue
		A_recent[c]=pd.to_numeric(A_recent[c])


	# get old detections
	B=pd.read_csv(config.outfile)

	# convert linux time to datetime
	A_recent['datetime']= pd.to_datetime(A_recent.lightningTimestamp,unit='s')
	B['datetime'] = pd.to_datetime( B.lightningTimestamp,unit='s')

	# remove detections > X time ago
	A_recent=A_recent[A_recent['datetime']>(T0-config.duration).strftime('%Y%m%d %H%M%S.%f')]
	B = B[ B['datetime']>(T0-config.duration).strftime('%Y%m%d %H%M%S.%f')]


	# Calculate distance from each stroke to the volcano
	# & deal with encoding issue in volcanoe name
	X=np.array([])
	for i, row in A_recent.iterrows():
		if row.volcanoName:
			A_recent.loc[i,'volcanoName']=row.volcanoName.encode('utf-8')
		x=gps2dist_azimuth(row.lightningLatitude,row.lightningLongitude,row.volcanoLatitude,row.volcanoLongitude)[0]/1000.
		X=np.append(X,x)
	A_recent['nearestDistanceKm']=X

	# restric strokes to within the outer ring
	A_recent=A_recent[A_recent['nearestDistanceKm']<config.dist2]
	
	# convert lightningId to integer
	A_recent['lightningId'] = pd.to_numeric(A_recent['lightningId'])

	# get dataframe containing strokes that haven't already been alerted on
	A_new = A_recent[ ~A_recent.lightningId.isin(B.lightningId) ]

	return A_recent, A_new

def sort_by_time(df):

	# sort from most recent down to oldest
	df2=df.copy()
	df2.sort('datetime',inplace=True,ascending=False)
	df2.reset_index()

	return df2

def get_distances2(df,vlat,vlon):

	df2=df.copy()

	# get distance in km for all strokes to volcano nearest to most recent stroke
	X =np.array([gps2dist_azimuth(vlat,vlon,row.lightningLatitude,row.lightningLongitude)[0]/1000 for i,row in df.iterrows()])
	AZ=np.array([gps2dist_azimuth(vlat,vlon,row.lightningLatitude,row.lightningLongitude)[1] for i,row in df.iterrows()])
	
	df2['latest_distance']=X
	df2['latest_azimuth']=AZ
	return df2

def get_distances(df):

	df2=df.copy()

	# get distance in km for all strokes to volcano nearest to most recent stroke
	X =np.array([gps2dist_azimuth(df.iloc[0].volcanoLatitude,df.iloc[0].volcanoLongitude,row.lightningLatitude,row.lightningLongitude)[0]/1000 for i,row in df.iterrows()])
	AZ=np.array([gps2dist_azimuth(df.iloc[0].volcanoLatitude,df.iloc[0].volcanoLongitude,row.lightningLatitude,row.lightningLongitude)[1] for i,row in df.iterrows()])
	
	df2['latest_distance']=X
	df2['latest_azimuth']=AZ
	return df2

def inner_outer(X,config):

	n_ring1=len(X[X<config.dist1])
	Y=X[X>config.dist1]
	n_ring2=len(Y[Y<config.dist2])

	return n_ring1, n_ring2

def get_direction(azimuth):
	dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
	ix = int(np.round(azimuth / (360. / len(dirs))))
	
	return dirs[ix % len(dirs)]

def create_message(A_recent,A_new,config):
	# create the subject line
	subject='--- {} Lightning ---'.format(A_recent.iloc[0].volcanoName)	

	# create the test for the message you want to send
	if len(A_new)==1:
		message='\n{} new stroke! ({} total)'.format(len(A_new),len(A_recent))
	else:
		message='\n{} new strokes! ({} total)'.format(len(A_new),len(A_recent))
	message='{}\n\n-- Most recent --'.format(message)
	t=pd.Timestamp(A_recent.iloc[0].datetime,tz='UTC')
	message='{}\n{} (UTC)'.format(message,t.strftime('%Y-%m-%d %H:%M:%S'))
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	message='{}\n{} ({})'.format(message,t_local.strftime('%Y-%m-%d %H:%M:%S'),t_local.tzname())
	message='{}\n{:.0f} km {} of {}'.format(message,A_recent.iloc[0].latest_distance,get_direction(A_recent.iloc[0].latest_azimuth),A_recent.iloc[0].volcanoName)
	message='{}\n\nData source: {}'.format(message,', '.join(A_new.dataSource.unique()).replace('EN','Earth Networks'))
	
	return subject, message

def plot_fig(A_recent, config, T0):
	import matplotlib as m
	m.use('Agg')
	from mpl_toolkits.basemap import Basemap
	import matplotlib.pyplot as plt
	from matplotlib.patches import Polygon
	from mpl_toolkits.axes_grid1.inset_locator import inset_axes
	from matplotlib.dates import date2num
	from PIL import Image

	dist=50
	lat0=A_recent.iloc[0].volcanoLatitude
	lon0=A_recent.iloc[0].volcanoLongitude
	dlat=1*(dist/111.1)
	dlon=dlat/np.cos(lat0*np.pi/180)
	latmin= lat0 - dlat
	latmax= lat0 + dlat
	lonmin= lon0 - dlon
	lonmax= lon0 + dlon

	m = Basemap(projection='merc',llcrnrlat=latmin,urcrnrlat=latmax,
							  llcrnrlon=lonmin,urcrnrlon=lonmax,lat_ts=lat0,resolution='h')		

	#Create figure
	plt.figure(figsize=(3.4,3.15))
	ax=plt.subplot(1,1,1)
	plt.title('--- {} Lightning ---\n{} UTC'.format(A_recent.iloc[0].volcanoName,A_recent.iloc[0].datetime.strftime('%Y-%m-%d %H:%M:%S')),fontsize=8)

	land_color='silver'
	water_color='lightblue'
	m.drawcoastlines(linewidth=0.5)
	m.drawmapboundary(fill_color=water_color)
	m.fillcontinents(color=land_color,lake_color=water_color)
	m.drawparallels([lat0-dlat/2,lat0+dlat/2],labels=[0,1,0,0],dashes=[8, 4],linewidth=0.2,fmt='%.2f',fontsize=6)
	m.drawmeridians([lon0-dlon/2,lon0+dlon/2],labels=[0,0,0,1],dashes=[8, 4],linewidth=0.2,fmt='%.2f',fontsize=6)
	m.drawmapscale(lon0-.7*dlon, lat0-.8*dlat, lon0, lat0, 15, barstyle='simple', units='km', fontsize=8, 
				    labelstyle='simple', fontcolor='k', linewidth=0.5, ax=None, format='%d', zorder=None)

	m.plot(lon0,lat0,'^',latlon=True,markeredgecolor='white',markerfacecolor='forestgreen',markersize=6,markeredgewidth=0.5)
	try:
		volcs=pd.read_csv('alarm_aux_files/volcanoes_kml.txt',delimiter='\t',names=['Volcano','kml','Lon','Lat'])
		volcs['dist']= [gps2dist_azimuth(lat,lon,lat0,lon0)[0]/1000 for lat,lon in zip(volcs.Lat.values,volcs.Lon.values)]
		volcs.sort_values('dist',inplace=True)
		m.plot(volcs.Lon.values[1:10],volcs.Lat.values[1:10],'^',latlon=True,markerfacecolor='forestgreen',markeredgecolor='black',markersize=4,markeredgewidth=0.5)
	except:
		pass

	m.ax = ax

	if len(A_recent)>1:
		G=A_recent.copy()
		G.sort('datetime',inplace=True,ascending=True)
		time=date2num(G.datetime)
		map_hdl=m.scatter(G.lightningLongitude.values,G.lightningLatitude.values,s=18,c=time,cmap='plasma',vmin=date2num((T0-config.duration).datetime), vmax=date2num(T0.datetime),edgecolors='k',linewidth=0.2,latlon=True,zorder=1e5)
		cbaxes = inset_axes(m.ax, height="70%", width="4%", loc=6,borderpad=-1) 
		cbar=plt.colorbar(map_hdl,cax=cbaxes,orientation='vertical')
		cbaxes.yaxis.set_ticks_position('left')
		cbar.set_ticks([date2num((T0-config.duration).datetime), date2num(T0.datetime)])
		cbar.set_ticklabels(['{:.0f}\nmin\nago'.format(config.duration/60.0),'Now'])
		cbar.ax.tick_params(labelsize=6)
	else:
		m.plot(A_recent.lightningLongitude.values,A_recent.lightningLatitude.values,'o',latlon=True,markerfacecolor='yellow',markeredgecolor='black',markersize=4,markeredgewidth=0.2)
	

    # Inset map.
	axin = inset_axes(m.ax, width="25%", height="25%", loc=1,borderpad=-1.5)
	latlims=[50.0,58.0]
	lonlims=[-189.9,-145]

	dist_inset=500
	lat0=A_recent.iloc[0].volcanoLatitude
	lon0=A_recent.iloc[0].volcanoLongitude
	dlat=1.75*(dist_inset/111.1)
	dlon=2*dlat/np.cos(lat0*np.pi/180)
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
	inmap.plot(lon0,lat0,'^',latlon=True,markerfacecolor='forestgreen',markeredgecolor='white',markersize=4,markeredgewidth=0.5)

	filename=os.environ['TMP_FIGURE_DIR']+'/'+UTCDateTime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
	plt.savefig(filename,dpi=300,format='png')
	plt.close()
	im=Image.open(filename)
	os.remove(filename)
	filename=filename+'.jpg'
	im.save(filename)
	return filename