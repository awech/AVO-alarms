# RSAM  alarm to be run on list of channels
# Based on MATLAB code originally written by Matt Haney and Aaron Wech
#
# Wech 2017-06-08

from . import utils
from obspy import UTCDateTime
import numpy as np
from pandas import DataFrame, Timestamp
import os
import time
import matplotlib as m
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import LinearSegmentedColormap

# main function called by main.py
def run_alarm(config,T0):

	time.sleep(config.latency)
	SCNL=DataFrame.from_dict(config.SCNL)
	lvlv=np.array(SCNL['value'])
	scnl=SCNL['scnl'].tolist()
	stas=[sta.split('.')[0] for sta in scnl]

	t1 = T0-config.duration
	t2 = T0
	st = utils.grab_data(scnl,t1,t2,fill_value=0)

	#### preprocess data ####
	st.detrend('demean')
	st.taper(max_percentage=None,max_length=config.taper_val)
	st.filter('bandpass',freqmin=config.f1,freqmax=config.f2)

	#### calculate rsam ####
	rms=np.array([np.sqrt(np.mean(np.square(tr.data))) for tr in st])

	#### calculate reduced displacement ####
	DR = []
	try:
		if hasattr(config,'VOLCANO_NAME'):
			DR = np.array([utils.RSAM_to_DR(tr,config.VOLCANO_NAME) for tr in st])
			print('Successfully calculated Reduced Displacement')
	except:
		pass

	############################# Icinga message #############################
	if any(DR):
		state_message = ''.join('{}: {:.0f}/{:.0f} (RD = {:.1f}), '.format(sta,rms[i],lvlv[i],DR[i]) for i,sta in enumerate(stas[:-1]))
	else:	
		state_message = ''.join('{}: {:.0f}/{:.0f}, '.format(sta,rms[i],lvlv[i]) for i,sta in enumerate(stas[:-1]))
	state_message = ''.join([state_message,'Arrestor ({}): {:.0f}/{:.0f}'.format(stas[-1],rms[-1],lvlv[-1])])
	state_message = ''.join([state_message,'[{:.0f} station minimum,{:g} -- {:g} Hz]'.format(config.min_sta,config.f1,config.f2)])
	###########################################################################

	if (rms[-1]<lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1])>=config.min_sta):
		#### RSAM Detection!! ####
		##########################
		print('********** DETECTION **********')
		state_message='{} (UTC) RSAM detection! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='CRITICAL'
		#
	elif (rms[-1]<lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1]/2)>=config.min_sta):
		#### elevated RSAM ####
		#######################
		state_message='{} (UTC) RSAM elevated! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	elif sum(rms[:-1]!=0)<config.min_sta:
		#### not enough data ####
		#########################
		state_message='{} (UTC) RSAM data missing! {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	elif (rms[-1]>=lvlv[-1]) & (sum(rms[:-1]>lvlv[:-1])>=config.min_sta):
		### RSAM arrested ###
		#####################
		state_message='{} (UTC) RSAM normal (arrested). {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='WARNING'
		#
	else:
		#### RSAM normal ####
		#####################
		state_message='{} (UTC) RSAM normal. {}'.format(T0.strftime('%Y-%m-%d %H:%M'),state_message)
		state='OK'


	if state=='CRITICAL':
		#### Generate Figure ####
		try:
			filename=make_figure(scnl,T0,config)
		except:
			filename=None
		
		### Craft message text ####
		subject, message = create_message(t1,t2,stas,rms,lvlv,DR,config.alarm_name)

		### Send message ###
		post_id = utils.post_mattermost(config, subject, message, filename)
		mm_link = os.environ["MATTERMOST_SERVER_URL"].replace("https", "mattermost")
		message = f"{message}\n\n{mm_link}/avo/pl/{post_id}"
		utils.send_alert(config.alarm_name, subject, message)
		# utils.send_alert(config.alarm_name,subject,message,filename)
		# utils.post_mattermost(config,subject,message,filename)
		# delete the file you just sent
		if filename:
			os.remove(filename)

	# send heartbeat status message to icinga
	utils.icinga2_state(config,state,state_message)


def create_message(t1,t2,stations,rms,lvlv,DR,alarm_name):

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

	a=np.array([''] * len(rms[:-1]))
	a[np.where(rms>lvlv)]='*'

	if any(DR):
		sta_message = ''.join('{}{}: {:.0f}/{:.0f} (RD = {:.1f})\n'.format(sta,a[i],rms[i],lvlv[i],DR[i]) for i,sta in enumerate(stations[:-1]))
	else:
		sta_message = ''.join('{}{}: {:.0f}/{:.0f}\n'.format(sta,a[i],rms[i],lvlv[i]) for i,sta in enumerate(stations[:-1]))
	sta_message = ''.join([sta_message,'\nArrestor: {} {:.0f}/{:.0f}'.format(stations[-1],rms[-1],lvlv[-1])])
	message = ''.join([message,sta_message])

	return subject, message


def make_figure(scnl,T0,config):
	m.use('Agg')

	plot_duration=3600
	if hasattr(config,'plot_duration'):
		plot_duration=config.plot_duration

	#### grab data ####
	start = time.time()	
	st = utils.grab_data(scnl,T0-plot_duration, T0,fill_value='interpolate')
	end = time.time()
	print('{:.2f} seconds to grab figure data.'.format(end - start))

	#### preprocess data ####
	st.detrend('demean')
	[tr.decimate(2,no_filter=True) for tr in st if tr.stats.sampling_rate==100]
	[tr.decimate(2,no_filter=True) for tr in st if tr.stats.sampling_rate==50]
	[tr.resample(25) for tr in st if tr.stats.sampling_rate!=25]

	
	
	plt.figure(figsize=(4.5,4.5))
	for i,tr in enumerate(st):
		if "BDF" in tr.stats.channel:
			ylabel_color = "red"
			colors=cm.viridis(np.linspace(-1,1.2,256))
		else:
			ylabel_color = "black"
			colors=cm.jet(np.linspace(-1,1.2,256))
		color_map = LinearSegmentedColormap.from_list('Upper Half', colors)
		ax=plt.subplot(len(st),1,i+1)
		tr.spectrogram(title='',log=False,samp_rate=25,dbscale=True,per_lap=0.5,mult=25.0,wlen=6,cmap=color_map,axes=ax)
		ax.set_yticks([3,6,9,12])
		ax.set_ylabel(tr.stats.station+'\n'+tr.stats.channel,fontsize=5,
															 color=ylabel_color,
															 rotation='horizontal',
													         multialignment='center',
													         horizontalalignment='right',
													         verticalalignment='center')
		ax.yaxis.set_ticks_position('right')
		ax.tick_params('y',labelsize=4)
		if i==0:
			ax.set_title(config.alarm_name+' Alarm')
		if i<len(st)-1:
			ax.set_xticks([])
		else:
			seis_tick_fmt='%H:%M'
			if plot_duration in [1800,3600,5400,7200]:
				n_seis_ticks=7
			elif plot_duration in [300,600,900,1200,1500,2100,2400,2700,3000,3300]:
				n_seis_ticks=6
			else:
				n_seis_ticks=6
				seis_tick_fmt='%H:%M:%S'
			d_sec=np.linspace(0,plot_duration,n_seis_ticks)
			ax.set_xticks(d_sec)
			T=[tr.stats.starttime+dt for dt in d_sec]
			ax.set_xticklabels([t.strftime(seis_tick_fmt) for t in T])
			ax.tick_params('x',labelsize=5)
			ax.set_xlabel(tr.stats.starttime.strftime('%Y-%m-%d')+' UTC')


	plt.subplots_adjust(left=0.08,right=.94,top=0.92,bottom=0.1,hspace=0.1)
	
	jpg_file=utils.save_file(plt,config,dpi=250)

	return jpg_file