from __future__ import division
import matplotlib as m
m.use('Agg')
import utils
from obspy import UTCDateTime
from obspy.core.util import AttribDict
import numpy as np
import pandas as pd
import os
import time
from obspy.signal.filter import envelope
from XC_loc import XC_main
# import sys_config


# main function called by alarm.py
def run_alarm(config,T0):

	time.sleep(config.latency+config.taper)
	state_message='{} (UTC) {}'.format(T0.strftime('%Y-%m-%d %H:%M'),config.alarm_name)
	CAT=pd.read_csv(config.catalog_file,delimiter='\t',parse_dates=['time'])
	CAT=CAT[CAT['time']>(T0-config.duration).strftime('%Y%m%d %H%M%S.%f')]

	#################################
	######### download data #########
	SCNL=pd.DataFrame.from_dict(config.SCNL)
	t1 = T0-1.5*config.window_length-config.taper
	t2 = T0+config.taper
	st = utils.grab_data(SCNL['scnl'].tolist(),t1,t2,fill_value=0)
	st = add_coordinate_info(st,SCNL)
	#################################
	

	#################################
	##### check for enough data #####
	Nsta=qc_checks(st)

	if Nsta<config.min_sta:
		state_message='{} - Data missing!'.format(state_message)
		state='WARNING'
		utils.icinga_state(config.alarm_name,state,state_message)
		return
    #################################
    

    #################################
	######## preprocess data ########
	band_env, high_env, band = preprocess(st,config,t1,t2)
	rsam_st=st.select(id=config.rsam_station)
	rsam_st.filter('bandpass',freqmin=config.f1,freqmax=config.f2,corners=3,zerophase=True)
	rsam=np.sqrt(np.mean(np.square(rsam_st[0].data)))
	#################################


	#################################
	######### get locations #########
	grid_file=None
	if hasattr(config,'grid_file') and os.path.exists(config.grid_file):
		grid_file=config.grid_file
	try:
		XC  = XC_main.XCOR(band_env,visual=False,bootstrap=config.bstrap,bootstrap_prct=config.bstrap_prct,
						Cmin=config.Cmin,Cmax=config.Cmax,env_hp=high_env,grid_size=config.grid,
						tt_file=grid_file,phase_types=config.phase_list)
	except:
		XC  = XC_main.XCOR(band_env,visual=False,bootstrap=config.bstrap,bootstrap_prct=config.bstrap_prct,
							Cmin=config.Cmin,Cmax=config.Cmax,env_hp=high_env,grid_size=config.grid)
		XC.save_traveltimes(config.grid_file)
	loc = XC.locate(window_length=config.window_length,step=config.window_length/2.,include_partial_windows=False)
	loc = loc.remove(max_scatter=config.max_scatter,inplace=False)
	loc = remove_hp_detects(loc)
	#################################
	

	#################################
	######## check past hour ########
	for l in loc.events:
		CAT=CAT.append(pd.DataFrame([[l.latitude,l.longitude,l.starttime.datetime]],columns=['lats','lons','time']))
	#################################


	#################################
	###### update catalog file ######
	CAT.to_csv(config.catalog_file,float_format='%.4f',index=False,sep='\t',date_format='%Y%m%dT%H%M%S.%f')
	#################################


	#################################
	##### create icinga message #####
	num_overlap        = len(np.where(np.diff(CAT['time'].values))[0]==config.window_length/2)
	duration           = (config.window_length*len(CAT)-(config.window_length/2)*num_overlap)/60
	duration_text = 'Correlated seismicity in {} of past {} minutes.'.format(minutes2string(duration),minutes2string(config.duration/60))
	if duration>0:
		last=UTCDateTime(pd.Timestamp(CAT.time.values[-1]).to_pydatetime())+config.window_length
		recency_text = 'Most recent: {} minutes ago'.format(minutes2string((T0-last)/60))
	else:
		duration_text = 'No correlated seismicity in the past {} minutes.'.format(minutes2string(config.duration/60))
		recency_text = ''
	recency_text = '{} {} RSAM:{:.0f}/{:.0f}'.format(recency_text, config.rsam_station.split('.')[1],rsam,config.rsam_threshold)

	####### set icinga statu##s #####
	if len(CAT)<config.threshold/2:
		state_message='{} - Normal seismicity. {} {}'.format(state_message,duration_text,recency_text)
		state='OK'
	elif len(CAT)>=config.threshold/2 and len(CAT)< config.threshold:
		state_message='{} - Elevated seismicity. {} {}'.format(state_message,duration_text,recency_text)
		state='WARNING'
	elif len(CAT)>config.threshold and rsam < config.rsam_threshold:
		state_message='{} - Tremor/Swarm detection, but low amplitude. {} {}'.format(state_message,duration_text,recency_text)
		state='WARNING'
	else:
		state_message='{} - Tremor/Swarm detection! {} {}'.format(state_message,duration_text,recency_text)
		state='CRITICAL'

        #### Generate Figure ####
		try:
			filename=make_figure(SCNL['scnl'].tolist(),T0,'Pavlof Tremor')
		except:
			filename=[]

        ### Craft message text ####
		subject, message = create_message(T0-config.duration,T0,config.alarm_name,duration_text)

        ### Send message ###
        utils.send_alert(config.alarm_name,subject,message,filename)
        utils.post_mattermost(config.alarm_name,subject,message,filename)
        # delete the file you just sent
        if filename:
            os.remove(filename)
	#################################

	utils.icinga_state(config.alarm_name,state,state_message)


def create_message(t1,t2,alarm_name,statement):
	from pandas import Timestamp

	# create the subject line
	subject='--- {} ---'.format(alarm_name)

	# create the text for the message you want to send
	message='Start: {} (UTC)\nEnd: {} (UTC)\n\n'.format(t1.strftime('%Y-%m-%d %H:%M'),t2.strftime('%Y-%m-%d %H:%M'))
	t1_local=Timestamp(t1.datetime,tz='UTC')
	t2_local=Timestamp(t2.datetime,tz='UTC')
	t1_local=t1_local.tz_convert(os.environ['TIMEZONE'])
	t2_local=t2_local.tz_convert(os.environ['TIMEZONE'])
	message='{}Start: {} ({})'.format(message,t1_local.strftime('%Y-%m-%d %H:%M'),t1_local.tzname())
	message='{}\nEnd: {} ({})\n\n'.format(message,t2_local.strftime('%Y-%m-%d %H:%M'),t2_local.tzname())
	message = ''.join([message,statement])

	return subject, message


def craft_and_send_email(t1,t2,alarm_name,filename,statement):
	from pandas import Timestamp

	# create the subject line
	subject='--- {} ---'.format(alarm_name)

	# create the text for the message you want to send
	message='Start: {} (UTC)\nEnd: {} (UTC)\n\n'.format(t1.strftime('%Y-%m-%d %H:%M'),t2.strftime('%Y-%m-%d %H:%M'))
	t1_local=Timestamp(t1.datetime,tz='UTC')
	t2_local=Timestamp(t2.datetime,tz='UTC')
	t1_local=t1_local.tz_convert(os.environ['TIMEZONE'])
	t2_local=t2_local.tz_convert(os.environ['TIMEZONE'])
	message='{}Start: {} ({})'.format(message,t1_local.strftime('%Y-%m-%d %H:%M'),t1_local.tzname())
	message='{}\nEnd: {} ({})\n\n'.format(message,t2_local.strftime('%Y-%m-%d %H:%M'),t2_local.tzname())
	message = ''.join([message,statement])


	utils.send_alert(alarm_name,subject,message,filename)
	utils.post_mattermost(subject,message,alarm_name,filename)
	# delete the file you just sent
	if filename:
		os.remove(filename)


def make_figure(scnl,T0,alarm_name):

	from alarm_codes.RSAM import make_figure
	filename=make_figure(scnl,T0,alarm_name)
	return filename


def minutes2string(min):
	if abs(min-np.round(min))<0.01:
		min_string='{:.0f}'.format(min)
	else:
		min_string='{:.1f}'.format(min)
	min_string=min_string.replace('-','')
	return min_string


def preprocess(st,config,t1,t2):
	st.detrend('demean')
	st.taper(max_percentage=None,max_length=config.taper)

	band=st.copy().filter('bandpass',freqmin=config.f1,freqmax=config.f2,corners=2,zerophase=True)
	high=st.copy().filter('highpass',freq=config.highpass,corners=2,zerophase=True)

	band_env=make_env(band.copy(),config,t1,t2)
	high_env=make_env(high,config,t1,t2)

	return band_env, high_env, band


def qc_checks(st):
	for tr in st:
		num_zeros=len(np.where(tr.data==0)[0])
        if num_zeros/float(tr.stats.npts)>0.03:
            st.remove(tr)
	lats=[]
	for tr in st:
		lats.append(tr.stats.coordinates.latitude)

	return len(np.unique(lats))

def remove_hp_detects(loc):
	A=loc.copy()
	for l in A.events:
		if l.highpass_loc:
			A.events.remove(l)
	return A

def make_env(st,config,t1,t2):
	new_st = st.copy()
	for tr in new_st:
		# if tr.stats['sampling_rate']==100:
		# 	tr.decimate(2)
		# if tr.stats['sampling_rate']==50:
		# 	tr.decimate(2)
		# if tr.stats['sampling_rate']!=25:
		# 	tr.resample(25.0)
		# tr.data = envelope(tr.data)
		if tr.stats.sampling_rate>21:
			tr.resample(25.0)
		if tr.stats.npts % 2 ==1:
			tr.trim(starttime=tr.stats.starttime,endtime=tr.stats.endtime+1/tr.stats.sampling_rate,pad=True,fill_value=0)
		tr.data = envelope(tr.data)
		tr.resample(5.0)

	new_st.filter('lowpass',freq=config.lowpass,corners=2,zerophase=True)
	# new_st.decimate(5)

	new_st.trim(t1+config.taper,t2-config.taper+1,fill_value=0,pad=True)

	return new_st


def add_coordinate_info(st,SCNL):
    #### compare remaining stations with lat/lon station info in config file
    #### to attach lat/lon info with each corresponding trace
    for tr in st:
        if tr.stats.location=='':
            tr.stats.location='--'
        tmp_scnl='{}.{}.{}.{}'.format(tr.stats.station,
                                      tr.stats.channel,
                                      tr.stats.network,
                                      tr.stats.location)
        tmp_lat=SCNL[SCNL['scnl']==tmp_scnl].lat.values[0]
        tmp_lon=SCNL[SCNL['scnl']==tmp_scnl].lon.values[0]
        tr.stats.coordinates=AttribDict({
                                'latitude': tmp_lat,
                                'longitude': tmp_lon,
                                'elevation': 0.0})
    return st