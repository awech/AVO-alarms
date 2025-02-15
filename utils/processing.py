import os
import re
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from numpy import cos, dtype, pi, round, zeros
from obspy import Catalog, Stream, Trace, UTCDateTime
from obspy.clients.earthworm import Client
from obspy.geodetics import gps2dist_azimuth
from pandas import DataFrame, read_excel
from PIL import Image
from tomputils import mattermost as mm

import requests
import urllib3
from obspy.io.quakeml.core import Unpickler
import numpy as np

import importlib
from glob import glob

import numpy as np
from obspy.clients.fdsn import Client
from obspy import read_inventory



def grab_data(scnl,T1,T2,fill_value=0):
    """_summary_

    Parameters
    ----------
    scnl : _type_
        _description_
    T1 : _type_
        _description_
    T2 : _type_
        _description_
    fill_value : int, optional
        _description_, by default 0

    Returns
    -------
    _type_
        _description_
    """
	# scnl = list of station names (eg. ['PS4A.EHZ.AV.--','PVV.EHZ.AV.--','PS1A.EHZ.AV.--'])
	# T1 and T2 are start/end obspy UTCDateTimes
	# fill_value can be 0 (default), 'latest', or 'interpolate'
	#
	# returns stream of traces with gaps accounted for
	#
	print('{} - {}'.format(T1.strftime('%Y.%m.%d %H:%M:%S'),T2.strftime('%Y.%m.%d %H:%M:%S')))
	print('Grabbing data...')

	st=Stream()

	t_test1=UTCDateTime.now()
	for sta in scnl:
		
		client = Client(os.environ['WINSTON_HOST'], int(os.environ['WINSTON_PORT']), timeout=int(os.environ['TIMEOUT']))
		if sta.split('.')[2] in ['HV','AM']:
			client = Client(os.environ['NEIC_HOST'], int(os.environ['NEIC_PORT']), timeout=int(os.environ['TIMEOUT']))

		try:
			tr=client.get_waveforms(sta.split('.')[2], sta.split('.')[0],sta.split('.')[3],sta.split('.')[1], T1, T2, cleanup=True)
			if len(tr)>1:
				print('{:.0f} traces for {}'.format(len(tr),sta))
				if fill_value==0 or fill_value==None:
					tr.detrend('demean')
					tr.taper(max_percentage=0.01)
				for sub_trace in tr:
					# deal with error when sub-traces have different dtypes
					if sub_trace.data.dtype.name != 'int32':
						sub_trace.data=sub_trace.data.astype('int32')
					if sub_trace.data.dtype!=dtype('int32'):
						sub_trace.data=sub_trace.data.astype('int32')
					# deal with rare error when sub-traces have different sample rates
					if sub_trace.stats.sampling_rate!=round(sub_trace.stats.sampling_rate):
						sub_trace.stats.sampling_rate=round(sub_trace.stats.sampling_rate)
				print('Merging gappy data...')
				tr.merge(fill_value=fill_value)
		except:
			tr=Stream()
		# if no data, create a blank trace for that channel
		if not tr:
			tr=Trace()
			tr.stats['station']=sta.split('.')[0]
			tr.stats['channel']=sta.split('.')[1]
			tr.stats['network']=sta.split('.')[2]
			tr.stats['location']=sta.split('.')[3]
			tr.stats['sampling_rate']=100
			tr.stats['starttime']=T1
			tr.data=zeros(int((T2-T1)*tr.stats['sampling_rate']),dtype='int32')
		st+=tr
	print('{} seconds'.format(UTCDateTime.now()-t_test1))
	
	print('Detrending data...')
	st.detrend('demean')
	st.trim(T1, T2, pad=True, fill_value=0)
	return st


def download_hypocenters(URL):
	
    """_summary_

    Returns
    -------
    _type_
        _description_
    """

    urllib3.disable_warnings()

	attempt = 1
	while attempt <= 3:
		try:
			res = requests.get(URL, verify=False, timeout=10)
			body = res.content
			break
		except:
			time.sleep(2)
			attempt+=1
			body = None

	if not body:
		return None	
	
	try:
		CAT = Unpickler().loads(body)
	except:
		CAT = Catalog()
		print('No events!')

	return CAT


def volcano_distance(lon0, lat0, volcs):
    """_summary_

    Parameters
    ----------
    lon0 : _type_
        _description_
    lat0 : _type_
        _description_
    volcs : _type_
        _description_

    Returns
    -------
    _type_
        _description_
    """

	DIST = np.array([])
	for lat, lon in zip(volcs.Latitude.values, volcs.Longitude.values):
		dist, azimuth, az2 = gps2dist_azimuth(lat, lon, lat0, lon0)
		DIST = np.append(DIST, dist/1000.)
	volcs.loc[:, 'distance'] = DIST

	return volcs


def update_stationXML():
    """_summary_
    """
	
	client = Client("IRIS")

	home_dir = Path(os.environ['HOME_DIR'])

	file_dir = home_dir / "alarm_configs" / "*RSAM*config.py"

	# files = glob(os.environ['HOME_DIR']+'/alarm_configs/*RSAM*config.py')
	files = glob(str(file_dir))
	SCNL = []

	for file in files:
		file = file.split('/')[-1].split('.')[0]
		config = importlib.import_module(f'.{file}', package='alarm_configs')
		print(config)
		if hasattr(config,'VOLCANO_NAME'):
			for scnl in config.SCNL:
				SCNL.append(scnl['scnl'])
	SCNL = np.array(SCNL)
	SCNL = np.unique(SCNL)

	print('______ Begin Updating Metadata ______')
	for scnl in SCNL:
		print(scnl)
		sta,chan,net,loc=scnl.split('.')
		if 'inventory' not in locals():
			inventory = client.get_stations(station=sta, network=net, channel=chan, location=loc, level='response', starttime=UTCDateTime.utcnow())
		else:
			inventory += client.get_stations(station=sta, network=net, channel=chan, location=loc, level='response', starttime=UTCDateTime.utcnow())

	write_path = home_dir / "alarm_aux_files" / "stations.xml"
	inventory.write(write_path, format = "STATIONXML")
	# inventory.write(os.environ['HOME_DIR']+'/alarm_aux_files/stations.xml',format='STATIONXML')

	print('^^^^^^ Finished Updating Metadata ^^^^^^')
	return


def Dr_to_RSAM(config, DR, volcano_name, base=25):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    DR : _type_
        _description_
    volcano_name : _type_
        _description_
    base : int, optional
        _description_, by default 25
    """
	

	client = Client("IRIS")
	home_dir = Path(os.environ['HOME_DIR'])

	
	VELOCITY = 1.5 	# km/s
	FREQ = 2 		# dominant frequency (Hz)
	Q = 200			# quality factor

	T0 = UTCDateTime.utcnow()
	VOLCS = read_excel(home_dir / "alarm_aux_files" / "volcano_list.xlsx")
	# VOLCS = read_excel('alarm_aux_files/volcano_list.xlsx')
	volcs = VOLCS[VOLCS['Volcano'] == volcano_name].copy()
	SCNL = DataFrame.from_dict(config.SCNL)

	for scnl in SCNL.scnl:

		sta, chan, net, loc = scnl.split('.')
		inventory = client.get_stations(network=net, 
									station=sta,
									channel=chan,
									location=loc,
									starttime=T0,
									endtime=T0,
									level='response')
		
		tr_id = '.'.join((net, sta, loc, chan)).replace('--', '')
		coords = inventory.get_coordinates(tr_id)
		gain = inventory.get_response(tr_id,T0).instrument_sensitivity.value # counts/m/s

		volcs = volcano_distance(coords['longitude'], coords['latitude'], volcs)
		R = volcs.iloc[0].distance


		# distance, velocity and wavelength in cm
		r = R * 1000 * 100
		velocity = VELOCITY * 1000 * 100
		wavelength = velocity / FREQ


		#### account for attenuation ####
		numerator = -np.pi * FREQ * r
		denominator = Q * velocity
		atten_factor = np.exp(numerator / denominator)


		rmssta = DR / np.sqrt(r * wavelength) 			# rms in cm
		rmssta_v = (rmssta * 2 * np.pi * FREQ) / 100 	# convert to velocity and change from cm to m (for the gain)
		lvl = rmssta_v * gain * atten_factor			# use gain to turn m/s to counts, and apply attenuation

		lvl = base * round(lvl / base)

		print('{}: {:g}'.format(scnl, lvl))

	return


def RSAM_to_DR(tr, volcano_name, VELOCITY=1.5, FREQ=2, Q=200):
    """_summary_
	


	VELOCITY = 1.5 	# km/s
	FREQ = 2 		# dominant frequency (Hz)
	Q = 200			# quality factor

    Parameters
    ----------
    tr : _type_
        _description_
    volcano_name : _type_
        _description_
    VELOCITY : float, optional
        _description_, by default 1.5
    FREQ : int, optional
        _description_, by default 2
    Q : int, optional
        _description_, by default 200

    Returns
    -------
    _type_
        _description_
		

    """

	home_dir = Path(os.environ['HOME_DIR'])
	VOLCS = read_excel(home_dir / "alarm_aux_files" / "volcano_list.xlsx")

	# VOLCS = read_excel('alarm_aux_files/volcano_list.xlsx')
	volcs = VOLCS[VOLCS['Volcano'] == volcano_name].copy()

	tr.id = tr.id.replace('--','')
	# inventory = read_inventory(os.environ['HOME_DIR']+'/alarm_aux_files/stations.xml')
	inventory = read_inventory(home_dir / "alarm_aux_files" / "stations.xml")

	coords = inventory.get_coordinates(tr.id)
	gain = inventory.get_response(tr.id, tr.stats.starttime).instrument_sensitivity.value # counts/m/s

	volcs = volcano_distance(coords['longitude'], coords['latitude'], volcs)
	R = volcs.iloc[0].distance

	r = R * 1000 * 100
	velocity = VELOCITY * 1000 * 100
	wavelength = velocity / FREQ


	#### account for attenuation ####
	numerator = -np.pi * FREQ * r
	denominator = Q * velocity
	atten_factor = np.exp(numerator / denominator)


	lvl = np.sqrt(np.mean(np.square(tr.data))) 	# rms level in counts
	rms_v = lvl / (gain * atten_factor)			# rms in m/s corrected for gain & attenuation
	rmssta = rms_v * 100 / (2 * np.pi * FREQ)	# converted to cm
	DR = rmssta * np.sqrt(r * wavelength)		# converted to reduced displacement

	return DR