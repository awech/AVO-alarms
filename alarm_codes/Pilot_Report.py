import pandas as pd
from obspy import UTCDateTime
from urllib import urlretrieve
from zipfile import ZipFile
import numpy as np
import os
import utils
# import sys_config
import socket
socket.setdefaulttimeout(15)

def run_alarm(config,T0):

	state_message='{} (UTC) No new pilot reports'.format(T0.strftime('%Y-%m-%d %H:%M'))
	state='OK'

	volcs=pd.read_csv('alarm_aux_files/volcanoes_kml.txt',delimiter='\t',names=['Volcano','kml','Lon','Lat'])	

	T2=T0
	T1=T2-config.cron_interval
	filetype='shp'
	t1='&year1={}&month1={}&day1={}&hour1={}&minute1={}'.format(T1.strftime('%Y'),
																T1.strftime('%m'),
																T1.strftime('%d'),
																T1.strftime('%H'),
																T1.strftime('%M'))
	t2='&year2={}&month2={}&day2={}&hour2={}&minute2={}'.format(T2.strftime('%Y'),
																T2.strftime('%m'),
																T2.strftime('%d'),
																T2.strftime('%H'),
																T2.strftime('%M'))
	new_url='{}?fmt={}{}{}'.format(os.environ['NOAA_CIMSS_URL'],filetype,t1,t2)

	try:
		urlretrieve(new_url, config.zipfilename)
	except:
		print('urlretrieve error')
		return
	try:
		archive = ZipFile(config.zipfilename, 'r')
	except:
		print('No new pilot reports')
		os.remove(config.zipfilename)
		utils.icinga_state(config.alarm_name,state,state_message)
		return
		# utils.icinga_state(config.alarm_name,state,state_message)

	# some data to parse, so import the relevant libraries (no need to do this if nothing downloaded)
	import shapefile
	from shutil import rmtree
	from obspy.geodetics.base import gps2dist_azimuth



	archive.extractall(path=config.tmp_zipped_dir)
	#shp_path=config.tmp_zipped_dir+'/stormattr_{}_{}'.format(T1.strftime('%Y%m%d%H%M'),T2.strftime('%Y%m%d%H%M'))
	shp_path=config.tmp_zipped_dir+'/pireps_{}_{}'.format(T1.strftime('%Y%m%d%H%M'),T2.strftime('%Y%m%d%H%M'))


	#read file, parse out the records and shapes
	sf = shapefile.Reader(shp_path)
	fields = [x[0] for x in sf.fields][1:]
	records = sf.records()
	shps = [s.points for s in sf.shapes()]


	#write into a dataframe
	df = pd.DataFrame(columns=fields, data=records)
	df['VALID']=pd.to_datetime(df['VALID'])
	df=df[df.LAT>49]


	#### delete duplicate events with different text versions in the 'REPORT' field'
	A=df.copy()
	del A['REPORT']
	A.drop_duplicates(inplace=True)
	df=df.ix[A.index]
	df.reset_index(drop=True,inplace=True)

	OLD = get_old_pireps(config,T0)

	for i, report in enumerate(df.REPORT.values):

		tmp_t = df.ix[i].VALID
		latstr = str(df.ix[i].LAT-np.floor(df.ix[i].LAT)).split('.')[1][:3]
		lonstr = str(-df.ix[i].LON-np.floor(-df.ix[i].LON)).split('.')[1][:3]
		latlon = int('{}{}'.format(latstr,lonstr))
		tmp_t = tmp_t + pd.to_timedelta(latlon,'us')
		tmp = pd.DataFrame(data={'lats':df.ix[i].LAT.astype('float'),
							 	 'lons':df.ix[i].LON.astype('float'),
							 	 'time':tmp_t}, index=[0])
		tmp.set_index('time',inplace=True)

		# if OLD.index.duplicated().any():
		# 	A = OLD[~OLD.index.duplicated()]
		# 	tmp1=tmp[~tmp.isin(A).all(1)]
		# 	A = OLD[OLD.index.duplicated()]
		# 	tmp2=tmp[~tmp.isin(A).all(1)]
		# 	tmp=tmp1+tmp2
		# else:
		tmp=tmp[~tmp.isin(OLD).all(1)]

		if tmp.empty:
			continue

		trigger = check_volcano_mention(report)
		
		if trigger:

			state_message='{} (UTC) {}'.format(T0.strftime('%Y-%m-%d %H:%M'),report)

			DIST=np.array([])
			for lat,lon in zip(volcs.Lat.values,volcs.Lon.values):
				dist, azimuth, az2=gps2dist_azimuth(lat,lon,df.ix[i].LAT,df.ix[i].LON)
				DIST=np.append(DIST,dist/1000.)

			if DIST.min()<config.max_distance:
				if df.ix[i].URGENT=='F':
					state = 'WARNING'
					config.send_email = config.non_urgent
				elif df.ix[i].URGENT=='T':
					state = 'CRITICAL'
					config.send_email = True

				A=volcs.copy()
				A['dist']=DIST

				UTC_time_text = '{} UTC'.format(UTCDateTime(df.ix[i].VALID).strftime('%Y-%m-%d %H:%M'))
				height_text   = get_height_text(report)
				pilot_remark  = get_pilot_remark(report)

				#### Generate Figure ####
				try:
					filename=plot_fig(df,i,A,UTC_time_text,height_text,pilot_remark)
				except:
					filename=[]

				### Craft message text ####
				subject, message = create_message(df,i,A,UTC_time_text,height_text,pilot_remark)

		        ### Send message ###
		        utils.send_alert(config.alarm_name,subject,message,filename)
		        utils.post_mattermost(config.alarm_name,subject,message,filename)

                # delete the file you just sent
		        if filename:
		            os.remove(filename)

				OLD = OLD.append(tmp)

	OLD.to_csv(config.outfile,float_format='%.6f',index_label='time',sep='\t',date_format='%Y%m%dT%H%M%S.%f')
	os.remove(config.zipfilename)
	rmtree(config.tmp_zipped_dir)
	utils.icinga_state(config.alarm_name,state,state_message)


def check_volcano_mention(report):
	trigger = False
	report=report.upper()
	tmp_report=report.replace('VAR','')
	tmp_report=tmp_report.replace('VAL','')
	tmp_report=tmp_report.replace('VAT','')
	tmp_report=tmp_report.replace('NEVA','')
	tmp_report=tmp_report.replace('AVAIL','')
	tmp_report=tmp_report.replace('SVA','')
	tmp_report=tmp_report.replace('PREVAIL','')
	tmp_report=tmp_report.replace('VASI','')
	tmp_report=tmp_report.replace('TOLOVANA','')
	tmp_report=tmp_report.replace('GAVANSKI','')
	tmp_report=tmp_report.replace('CORDOVA','')
	tmp_report=tmp_report.replace('ADVANC','')
	tmp_report=tmp_report.replace('INVAD','')
	tmp_report=tmp_report.replace('VACINITY','')
	tmp_report=tmp_report.replace('SULLIVAN','')
	tmp_report=tmp_report.replace('BELIEVABLE','')
	if len(tmp_report.split('/SK'))>1 and 'VA' in tmp_report.split('/SK')[-1].split('/')[0]:
		trigger = True
	elif len(tmp_report.split('/RM'))>1 and 'VA' in tmp_report.split('/RM')[-1].split('/')[0]:
		trigger = True	
	elif ' ASH' in report:
		trigger = True
	elif '/ASH' in report:
		trigger = True
	elif 'VOLC' in report:
		trigger = True
	elif 'SULFUR' in report:
		trigger = True
	elif 'PLUME' in report:
		trigger = True
	elif 'ERUPT' in report:
		trigger = True
	elif 'STEAM' in report:
		trigger = True
	elif 'MAGMA' in report:
		trigger = True
	elif 'PYROCLASTIC' in report:
		trigger = True

	return trigger


def get_old_pireps(config,T0):

	OLD=pd.read_csv(config.outfile,delimiter='\t',parse_dates=['time'])
	OLD=OLD.drop_duplicates(keep=False)
	OLD=OLD[OLD['time']>(T0-config.cron_interval-10).strftime('%Y%m%d %H%M%S.%f')]

	OLD['lats']=OLD.lats.values.astype('float')
	OLD['lons']=OLD.lons.values.astype('float')

	OLD.set_index('time',inplace=True)

	return OLD


def get_height_text(report):
	height = report.split('/FL')[-1].split('/')[0]
	try:		
		height_text = 'Flight level: {:.0f},000 feet asl'.format(int(height)/10.)
	except:
		height_text = 'Flight level: UNKNOWN'

	return height_text


def get_pilot_remark(report):
	import re
	
	FL = re.compile('(.*)fl(\d+)(.*)', re.MULTILINE)
	RM = re.compile('(RM)*(.*)')

	fields = report.split('/')
	pilot_remark = 'Pilot Remark: {}'.format(RM.sub(r'\2',fields[-1]).lower().lstrip())
	t1=FL.sub(r'\1',pilot_remark)
	t2=FL.sub(r'\2',pilot_remark)
	t3=FL.sub(r'\3',pilot_remark)
	try:
		pilot_remark='{}{:.0f},000 feet asl{}'.format(t1,int(t2)/10.,t3)
	except:
		pass

	return pilot_remark


def create_message(df,i,A,UTC_time_text,height_text,pilot_remark):

	t=pd.Timestamp(df.ix[i].VALID,tz='UTC')
	t_local=t.tz_convert(os.environ['TIMEZONE'])
	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'),t_local.tzname())


	message = '{}\n{}\n{}\n{}'.format(UTC_time_text,Local_time_text,height_text,pilot_remark)
	message = '{}\nLatitude: {:.3f}\nLongitude: {:.3f}\n'.format(message,df.ix[i].LAT,df.ix[i].LON)

	v_text=''
	for candidate in A.sort_values('dist').Volcano.values[:3]:
		v_text='{}{}, '.format(v_text,candidate)
	v_text=v_text.replace('_',' ')
	message = '{}Nearest volcanoes: {}\n'.format(message,v_text[:-2])
	message = '{}\n--Original Report--\n{}'.format(message,df.ix[i].REPORT)
	print(message)

	if df.ix[i].URGENT=='T':
		subject = 'URGENT! Activity possible at: {}'.format(v_text[:-2])
	else:
		subject = 'Activity possible at: {}'.format(v_text[:-2])

	return subject, message

# def craft_and_send_email(df,i,A,UTC_time_text,height_text,pilot_remark,attachment,config):

# 	t=pd.Timestamp(df.ix[i].VALID,tz='UTC')
# 	t_local=t.tz_convert(os.environ['TIMEZONE'])
# 	Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'),t_local.tzname())


# 	message = '{}\n{}\n{}\n{}'.format(UTC_time_text,Local_time_text,height_text,pilot_remark)
# 	message = '{}\nLatitude: {:.3f}\nLongitude: {:.3f}\n'.format(message,df.ix[i].LAT,df.ix[i].LON)

# 	v_text=''
# 	for candidate in A.sort_values('dist').Volcano.values[:3]:
# 		v_text='{}{}, '.format(v_text,candidate)
# 	v_text=v_text.replace('_',' ')
# 	message = '{}Nearest volcanoes: {}\n'.format(message,v_text[:-2])
# 	message = '{}\n--Original Report--\n{}'.format(message,df.ix[i].REPORT)
# 	print(message)

# 	if df.ix[i].URGENT=='T':
# 		subject = 'URGENT! Activity possible at: {}'.format(v_text[:-2])
# 	else:
# 		subject = 'Activity possible at: {}'.format(v_text[:-2])

# 	if config.send_email:
# 		utils.send_alert(config.alarm_name,subject,message,attachment)
# 	utils.post_mattermost(config.alarm_name,subject,message,filename=attachment)

# 	# delete the file you just sent
# 	if attachment:
# 		os.remove(attachment)


def plot_fig(df,i,A,UTC_time_text,height_text,pilot_remark):
	import matplotlib as m
	m.use('Agg')
	from mpl_toolkits.basemap import Basemap
	import matplotlib.pyplot as plt
	from matplotlib.patches import Polygon
	from mpl_toolkits.axes_grid1.inset_locator import inset_axes
	from PIL import Image
	from textwrap import wrap

	latlims=[df.ix[i].LAT-2,df.ix[i].LAT+2]
	lonlims=[df.ix[i].LON-4,df.ix[i].LON+4]
	m = Basemap(projection='tmerc',llcrnrlat=latlims[0],urcrnrlat=latlims[1],
								  llcrnrlon=lonlims[0],urcrnrlon=lonlims[1],lat_0=df.ix[i].LAT,lon_0=df.ix[i].LON,
								  resolution='i',area_thresh=25.0)

	#Create figure
	fig, ax = plt.subplots(figsize=(4,4))

	m.drawcoastlines()
	m.drawmapboundary(fill_color='gray')
	m.fillcontinents(color='black',lake_color='gray')
	m.plot(df.ix[i].LON,df.ix[i].LAT,'yo',latlon=True,markeredgecolor='white',markersize=6,markeredgewidth=0.5)
	m.plot(A.sort_values('dist').Lon.values[:10],A.sort_values('dist').Lat.values[:10],'^r',latlon=True,markeredgecolor='black',markersize=4,markeredgewidth=0.5)
	plt.title(UTC_time_text+'\n'+height_text)


	parallels=np.array([np.round(df.ix[i].LAT*10)/10.-0.8,np.round(df.ix[i].LAT*10)/10.+0.8])
	meridians=np.array([np.round(df.ix[i].LON*10)/10.-1.5,np.round(df.ix[i].LON*10)/10.+1.5])
	m.drawparallels(parallels,color='w',textcolor='k',linewidth=0.5,dashes=[1,4],labels=[False,True,False,True],fontsize=6)
	m.drawmeridians(meridians,color='w',textcolor='k',linewidth=0.5,dashes=[1,4],labels=[False,True,False,True],fontsize=6)
	plt.xlabel('\n'.join(wrap(pilot_remark,60)),labelpad=10,fontsize=8)

	m.ax = ax

    # Inset map.
	axin = inset_axes(m.ax, width="25%", height="25%", loc=1,borderpad=0.3)
	latlims=[50.0,58.0]
	lonlims=[-189.9,-145]
	# inmap = Basemap(projection='tmerc',llcrnrlat=df.ix[i].LAT-20,urcrnrlat=df.ix[i].LAT+20,
	# 							  llcrnrlon=df.ix[i].LON-50,urcrnrlon=df.ix[i].LON+50,lat_0=np.mean(latlims),lon_0=np.mean(lonlims),resolution='l')

	inmap = Basemap(projection='eqdc',lat_1=latlims[0],lat_2=latlims[1],
					lat_0=df.ix[i].LAT,lon_0=df.ix[i].LON,width=3500000,height=3000000,
					resolution='i',area_thresh=100.0)

	inmap.drawcountries(color='0.2',linewidth=0.5)
	inmap.fillcontinents(color='gray')
	inmap.drawmapboundary(color='white',fill_color='gray')
	inmap.fillcontinents(color='black',lake_color='gray')
	bx, by = inmap(m.boundarylons, m.boundarylats)
	xy = list(zip(bx, by))
	mapboundary = Polygon(xy, edgecolor='y', linewidth=1, fill=False)
	axin.add_patch(mapboundary)

	filename=os.environ['TMP_FIGURE_DIR']+'/'+UTCDateTime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
	plt.savefig(filename,dpi=250,format='png')
	plt.close()
	im=Image.open(filename)
	os.remove(filename)
	filename=filename+'.jpg'
	im.save(filename)
	return filename
