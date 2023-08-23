from . import utils
import os
from io import BytesIO
import pandas as pd
import numpy as np
import utm
from obspy.io.quakeml.core import Unpickler
from obspy import Catalog, UTCDateTime, Inventory
from obspy.geodetics.base import gps2dist_azimuth
import cartopy
from cartopy.io.img_tiles import GoogleTiles
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import pycurl
import matplotlib.pyplot as plt
from matplotlib.dates import date2num, num2date
import matplotlib as m
from matplotlib.path import Path
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import shapely.geometry as sgeom
from itertools import combinations
import warnings
import traceback
import time
from obspy.clients.fdsn import Client
from sklearn.cluster import DBSCAN


attempt = 1
while attempt <= 3:
	try:
		client = Client('IRIS')
		break
	except:
		time.sleep(2)
		attempt+=1
		client = None


def run_alarm(config, T0):

	# Download the event data
	print(T0.strftime('%Y-%m-%d %H:%M'))
	print('Downloading events...')
	config.DURATION = np.array([swm['MAX_EVT_TIME'] for swm in config.swarm_parameters]).max()
	CAT = download_events(T0, config)

	# No events
	if len(CAT) == 0:
		state = 'OK'
		state_message = '{} (UTC) No new earthquakes'.format(T0.strftime('%Y-%m-%d %H:%M'))
		# utils.icinga2_state(config, state, state_message)
		return

	# filter out regional VTs
	print('Filtering out regional VTs')
	VOLCS = pd.read_excel(config.volc_file)
	VOLCS = VOLCS[VOLCS['Holocene']=='Y']
	CAT_DF = catalog_to_dataframe(CAT, VOLCS)
	CAT_DF = CAT_DF[CAT_DF['V_DIST']<config.VOLCANO_DISTANCE]
	CAT_DF = CAT_DF.reset_index(drop=True)

	# New events, but not close enough to volcanoes
	if len(CAT_DF) == 0:
		print('Earthquakes detected, but not near any volcanoes')
		state = 'OK'
		state_message = '{} (UTC) No new swarm activity'.format(T0.strftime('%Y-%m-%d %H:%M'))
		# utils.icinga2_state(config, state, state_message)
		return

	# Read in old events. Filter to new events
	OLD_EVENTS = pd.read_csv(config.outfile, sep='\t', parse_dates=['Time'])
	NEW_EVENTS = CAT_DF.loc[~CAT_DF['ID'].isin(OLD_EVENTS.ID)]

	# No new earthquakes
	if len(NEW_EVENTS) == 0:
		state = 'OK'
		state_message = '{} (UTC) No new earthquakes'.format(T0.strftime('%Y-%m-%d %H:%M'))
		# utils.icinga2_state(config, state, state_message)
		return

	# Check for swarms
	print('Clustering...')
	SWARMS = get_swarms(NEW_EVENTS.copy(), T0, config)

	# New events, but not swarm-y
	if len(SWARMS) == 0:
		ALL_EVENTS = pd.concat([OLD_EVENTS, NEW_EVENTS], keys='ID', ignore_index=True).drop_duplicates('ID')
		SWARM_CONTINUE = get_swarms(ALL_EVENTS.copy(), T0, config)
		SWARM_CONTINUE = [swarm.loc[~swarm['ID'].isin(OLD_EVENTS.ID)] for swarm in SWARM_CONTINUE]
		SWARM_CONTINUE = [swarm for swarm in SWARM_CONTINUE if len(swarm)>0]

		if len(SWARM_CONTINUE) > 0:
			print('Earthquakes detected. Continuation of swarm actvity')
			state = 'WARNING'
			v_list = [swarm.iloc[0].VOLCANO for swarm in SWARM_CONTINUE]
			state_message = '{} (UTC) Ongoing swarm actvity at: {}'.format(T0.strftime('%Y-%m-%d %H:%M'), ', '.join(np.unique(v_list)))

			MERGED_SWARMS = pd.concat(SWARM_CONTINUE, keys='ID', ignore_index=True).drop_duplicates('ID')
			ALL_EVENTS = pd.concat([OLD_EVENTS, MERGED_SWARMS], keys='ID', ignore_index=True).drop_duplicates('ID')
			ALL_EVENTS = ALL_EVENTS[ALL_EVENTS['Time'] > (T0 - config.DURATION).strftime('%Y-%m-%d %H:%M:%S')]
			ALL_EVENTS = ALL_EVENTS.sort_values('Time')
			ALL_EVENTS[['ID','Time','Latitude','Longitude','VOLCANO']].to_csv(config.outfile, index=False, sep='\t', float_format='%.3f')
		else:
			print('Earthquakes detected, but no new swarm actvity')
			state = 'OK'
			state_message = '{} (UTC) No new swarm actvity'.format(T0.strftime('%Y-%m-%d %H:%M'))

			ALL_EVENTS = OLD_EVENTS[OLD_EVENTS['Time'] > (T0 - config.DURATION).strftime('%Y-%m-%d %H:%M:%S')]
			ALL_EVENTS = ALL_EVENTS.sort_values('Time')
			ALL_EVENTS[['ID','Time','Latitude','Longitude','VOLCANO']].to_csv(config.outfile, index=False, sep='\t', float_format='%.3f')

		# utils.icinga2_state(config, state, state_message)
		return


	# remove duplicate or overlapping swarms
	SWARMS = compare_swarms(SWARMS)

	# Combine old and new swarm detects. Write out all combined events within T0 - max(duration)
	MERGED_SWARMS = pd.concat(SWARMS, keys='ID', ignore_index=True).drop_duplicates('ID')
	ALL_EVENTS = pd.concat([OLD_EVENTS, MERGED_SWARMS], keys='ID', ignore_index=True).drop_duplicates('ID')
	ALL_EVENTS = ALL_EVENTS[ALL_EVENTS['Time'] > (T0 - config.DURATION).strftime('%Y-%m-%d %H:%M:%S')]
	ALL_EVENTS = ALL_EVENTS.sort_values('Time')
	ALL_EVENTS[['ID','Time','Latitude','Longitude','VOLCANO']].to_csv(config.outfile, index=False, sep='\t', float_format='%.3f')

	for swarm in SWARMS:
		state = 'CRITICAL'
		state_message = '{} (UTC) Swarm actvity at: {}'.format(T0.strftime('%Y-%m-%d %H:%M'), swarm.iloc[0].VOLCANO)

		subject, message = create_message(swarm)
		print(subject)
		print(message)

		#### Generate Figure ####
		try:
			# stations = get_swarm_stations(swarm)
			attachment = plot_event(swarm, T0, config, VOLCS, CAT)
			new_filename = '{}/{}_M{:.1f}_{}.png'.format(os.environ['TMP_FIGURE_DIR'],
												 swarm.iloc[0].Time.strftime('%Y%m%dT%H%M%S'),
												 swarm.iloc[0].Magnitude,
												 ''.join(swarm.iloc[0].ID.split('/')[-2:]).lower())
			os.rename(attachment, new_filename)
			attachment = new_filename
		except:
			attachment = []
			print('Problem making figure. Continue anyway')
			b = traceback.format_exc()
			err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
			print(err_message)

		# print('Sending message...')
		# utils.send_alert(config.alarm_name, subject, message, filename=attachment)
		print('Posting message to Mattermost...')
		utils.post_mattermost(config, subject, message, filename=attachment)
		if attachment:
			os.remove(attachment)



def get_extent(lat0, lon0, dist=20):

	dlat = 1*(dist/111.1)
	dlon = dlat/np.cos(lat0*np.pi/180)

	latmin= lat0 - dlat
	latmax= lat0 + dlat
	lonmin= lon0 - dlon
	lonmax= lon0 + dlon

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


class ShadedReliefESRI(GoogleTiles):
	# shaded relief
	def _image_url(self, tile):
		x, y, z = tile
		url = ('https://server.arcgisonline.com/ArcGIS/rest/services/' \
			   'World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}.jpg').format(
			   z=z, y=y, x=x)
		return url


def plot_event(swarm, T0, config, VOLCS, CAT):
	m.use('Agg')
	n_blank = 4

	channels = get_swarm_stations(swarm, CAT)
	channels = channels.sort_values('count', ascending=False)

	fig, ax = plt.subplot_mosaic(
		[
			['map'],
			['stem']
		],
		figsize=(4,5.5),
		height_ratios=[3,1],
		layout="constrained",
		per_subplot_kw={"map":{"projection":ShadedReliefESRI().crs}}
	)

	#################### Add main map ####################
	volcs = utils.volcano_distance(swarm.iloc[0].Longitude, swarm.iloc[0].Latitude, VOLCS)
	volcs = volcs.sort_values('distance')

	# grid = plt.GridSpec(1, 1, wspace=0.05, hspace=0.6)
	print('Plotting main map...')
	extent = get_extent(volcs.iloc[0].Latitude, volcs.iloc[0].Longitude, dist=15)
	ax['map'].set_extent(extent)
	ax['map'].add_image(ShadedReliefESRI(), 11)
	lon_grid = [np.mean(extent[:2])-np.diff(extent[:2])[0]/4, np.mean(extent[:2])+np.diff(extent[:2])[0]/4]
	lat_grid = [np.mean(extent[-2:])-np.diff(extent[-2:])[0]/4, np.mean(extent[-2:])+np.diff(extent[-2:])[0]/4]
	gl = ax['map'].gridlines(draw_labels={"bottom": "x", "right": "y"},
					   xlocs=lon_grid, ylocs=lat_grid,
					   xformatter=LongitudeFormatter(number_format='.2f', direction_label=False),
					   yformatter=LatitudeFormatter(number_format='.2f', direction_label=False),
					   alpha=0.2, 
					   color='gray', 
					   linewidth=0.5,
					   xlabel_style={'fontsize':6},
					   ylabel_style={'fontsize':6})

	ax['map'].plot(volcs[:10].Longitude, volcs[:10].Latitude, '^', markerfacecolor='k', markersize=7, markeredgecolor='w', markeredgewidth=0.3, transform=cartopy.crs.PlateCarree())
	ax['map'].plot(channels.Longitude, channels.Latitude, 's', markerfacecolor='dimgrey', markersize=4, markeredgecolor='k', markeredgewidth=0.6, transform=cartopy.crs.PlateCarree())

	time = date2num(swarm.Time)
	map_hdl = ax['map'].scatter(swarm.Longitude.values, 
				swarm.Latitude.values, 
				s=40, 
				c=time,
				cmap='plasma', 
				vmin=date2num((T0-swarm.iloc[0].param_duration).datetime), 
				vmax=date2num(T0.datetime),
				marker='o', 
				edgecolors='k', 
				linewidth=0.5, 
				transform=cartopy.crs.PlateCarree(), 
				zorder=1e4)

	cbaxes = inset_axes(ax['map'], height="70%", width="3%", loc=6, borderpad=-1.1) 
	cbar = plt.colorbar(map_hdl, cax=cbaxes, orientation='vertical')
	cbaxes.yaxis.set_ticks_position('left')
	cbar.set_ticks([date2num((T0-swarm.iloc[0].param_duration).datetime), date2num(T0.datetime)])
	cbar.set_ticklabels(['{:.0f}\nhour\nago'.format(swarm.iloc[0].param_duration/3600.0), 'Now'])
	cbar.ax.tick_params(labelsize=6)
	
	ax['map'].set_title('{} events\nFirst:	 {} UTC\nLatest:  {} UTC'.format(len(swarm),
													   swarm.Time.min().strftime('%Y-%m-%d %H:%M'), 
													   swarm.Time.max().strftime('%Y-%m-%d %H:%M')),
				  fontsize=8)


	################### Add inset map ###################
	print('Plotting inset map...')
	extent2 = get_extent(volcs.iloc[0].Latitude, volcs.iloc[0].Longitude, dist=150)
	CRS2 = cartopy.crs.AlbersEqualArea(central_longitude=np.mean(extent2[:2]), central_latitude=np.mean(extent[2:]), globe=None)
	glb_ax = fig.add_axes([0.75, 0.84, 0.17, 0.17], projection=CRS2)
	glb_ax.set_boundary(make_path(extent2), transform=cartopy.crs.Geodetic())
	glb_ax.set_extent(extent2,cartopy.crs.Geodetic())
	coast = cartopy.feature.GSHHSFeature(scale="intermediate", rasterized=True)
	glb_ax.add_feature(coast, facecolor="lightgray", linewidth=0.1)
	extent_lons=np.concatenate( (np.linspace(extent[0],extent[1],100),
								 extent[1]*np.ones(100),
								 np.linspace(extent[1],extent[0],100),
								 extent[0]*np.ones(100)
								)
							  )
	extent_lats=np.concatenate( (extent[2]*np.ones(100),
								 np.linspace(extent[2],extent[3],100),
								 extent[3]*np.ones(100),
								 np.linspace(extent[3],extent[2],100),
								)
							  )
	pointList = [sgeom.Point(x,y) for x,y in zip(extent_lons,extent_lats)]
	poly = sgeom.Polygon([[p.x, p.y] for p in pointList])
	glb_ax.add_geometries([poly], cartopy.crs.Geodetic(), facecolor='none', edgecolor='crimson', linewidth=.75,zorder=1e3)
	#####################################################

	mag_swarm = swarm[~swarm['Magnitude'].isnull()]
	time = date2num(mag_swarm.Time)
	markerline, stemlines, baseline = ax['stem'].stem(mag_swarm.Time, mag_swarm.Magnitude,
													  linefmt='k-',
													  markerfmt='k.',
													  bottom=-5,
													  )
	stemlines.set_linewidth(0.8)
	ax['stem'].scatter(mag_swarm.Time, mag_swarm.Magnitude,
					   s=30, 
					   c=time,
					   edgecolors='k',
					   linewidth=0.8, 
					   cmap='plasma', 
					   vmin=date2num((T0-swarm.iloc[0].param_duration).datetime), 
					   vmax=date2num(T0.datetime),
					   zorder=10,
					   label='_nolegend_'
					)
	ax['stem'].set_ylim(mag_swarm.Magnitude.min()-0.1,mag_swarm.Magnitude.max()+0.1)


	no_mag_swarm = swarm[swarm['Magnitude'].isnull()]
	time = date2num(no_mag_swarm.Time)
	h_no_mag = ax['stem'].scatter(no_mag_swarm.Time, np.ones_like(time)*ax['stem'].get_ylim()[0],
				   s=30, 
				   c='gray',
				   edgecolors='k',
				   linewidth=0.8, 
				   zorder=10,
				   clip_on=False,
				   label='No magnitude'
				)

	ax['stem'].set_xlim(date2num(T0-swarm.iloc[0].param_duration), date2num(T0))
	ticks = [t.strftime('%Y-%m-%d\n%H:%M') for t in num2date(ax['stem'].get_xticks())]

	ticks = [t.strftime('%Y-%m-%d\n%H:%M') if i % 2 !=0 else '' 
			 for i, t in enumerate(num2date(ax['stem'].get_xticks()))]


	ax['stem'].set_xticklabels(ticks, rotation = 45, ha='right', rotation_mode="anchor", fontsize=6)
	ax['stem'].tick_params(axis='x', which='major', pad=0)
	ax['stem'].set_yticklabels(ax['stem'].get_yticks(), fontsize=6)
	ax['stem'].set_ylabel('Magnitude')
	ax['stem'].grid(axis='both', linewidth=0.2,linestyle='--')

	if len(no_mag_swarm)>0:
		ax['stem'].legend(loc='upper right', markerscale=0.8, fontsize=6)


	jpg_file = utils.save_file(fig, config, dpi=250)
	plt.close(fig)

	return jpg_file


def get_swarm_stations(swarm, CAT):

	SWM_CAT = Catalog()
	for i, evt in swarm.iterrows():
		eq = CAT.filter(f"time >= {evt.Time}", f"time <= {evt.Time}")
		SWM_CAT += eq

	# Add phase info to new events
	try:
		SWM_CAT = addPhaseHint(SWM_CAT)
		flag = True
	except:
		print('Could not add phase type...')
		flag = False

	if flag:
		NSLC = []
		SCNL = []
		LATS = []
		LONS = []
		NS = []
		NS_COUNT = []
		for eq in SWM_CAT:
			for p in eq.picks:
				wid=p.waveform_id
				net, sta, loc, chan = wid.id.split('.')
				ns = '.'.join([net,sta])
				NS_COUNT.append(ns)
				if (ns not in NS):
					print('Getting lat/lon info for {}'.format(wid.id))
					inventory = client.get_stations(network=net,
													station=sta,
													location=loc,
													channel=chan)
					NS.append(ns)
					NSLC.append(wid.id)
					SCNL.append('.'.join([sta, chan, net, loc]))
					LATS.append(inventory[0][0].latitude)
					LONS.append(inventory[0][0].longitude)
					STAS = pd.DataFrame({'NS':NS, 'NSLC':NSLC, 'SCNL':SCNL, 'Latitude':LATS, 'Longitude':LONS})
	for ns in NS:
		STAS.loc[STAS['NS']==ns, 'count'] = int(len(np.where(np.array(NS_COUNT)==ns)[0]))

	return STAS


def create_message(swarm):

	tmin = pd.Timestamp(swarm.Time.min(), tz='UTC')
	tmax = pd.Timestamp(swarm.Time.max(), tz='UTC')
	dt = tmax - tmin
	hours = np.floor(dt.total_seconds()/3600)
	minutes = np.round((dt.total_seconds() - hours*3600)/60)

	message = '{} events in past {:.0f}h {:.0f}m, from:'.format(len(swarm), hours, minutes)
	message+= '\n\n{} - {} UTC'.format(tmin.strftime('%Y-%m-%d %H:%M'), tmax.strftime('%Y-%m-%d %H:%M'))
	tmin_local = tmin.tz_convert(os.environ['TIMEZONE'])
	tmax_local = tmax.tz_convert(os.environ['TIMEZONE'])
	message+= '\n{} - {} {}'.format(tmin_local.strftime('%Y-%m-%d %H:%M'), tmax_local.strftime('%Y-%m-%d %H:%M'), tmax_local.tzname())

	message+= '\n\nMagnitude range {:.1f} - {:.1f}'.format(swarm.Magnitude.min(), swarm.Magnitude.max())
	num_nan_mags = len(np.where(np.isnan(swarm.Magnitude))[0])
	if num_nan_mags == 1:
		message+=' ({:.0f} event with unassigned magnitude)'.format(num_nan_mags)
	elif num_nan_mags > 1:
		message+=' ({:.0f} events with unassigned magnitude)'.format(num_nan_mags)

	subject = 'Earthquake swarm at {}'.format(swarm.iloc[0].VOLCANO)

	return subject, message


def compare_swarms(SWARMS):
	flag = True
	TEST_SWARMS = SWARMS.copy()
	while flag:
		SWARM_COMBOS = list(combinations(range(len(TEST_SWARMS)), 2))

		if len(SWARM_COMBOS) > 0:
			remove_swarm_ind = []
			flag_list = []
			for ind_combo in SWARM_COMBOS:
				# check for duplicate swarm detections
				if TEST_SWARMS[ind_combo[0]].equals(TEST_SWARMS[ind_combo[1]]):
					print('found equals')
					flag_list.append(True)
					remove_swarm_ind.append(ind_combo[0])			
					continue

				# check for overlap, and keep the shortest duration event
				int_df = pd.merge(TEST_SWARMS[ind_combo[0]], TEST_SWARMS[ind_combo[1]], how ='inner', on =['ID', 'ID'])
				if len(int_df) > 0:
					print('overlap')
					dt0 = TEST_SWARMS[ind_combo[0]].Time.max() - TEST_SWARMS[ind_combo[0]].Time.min()
					dt1 = TEST_SWARMS[ind_combo[1]].Time.max() - TEST_SWARMS[ind_combo[1]].Time.min()
					remove_swarm_ind.append( ind_combo[np.argmax([dt0,dt1])] )
					flag_list.append(True)
				else:
					print('no overlap')
					flag_list.append(False)

			# update swarms list with duplicate/overlapping swarms removed
			TEST_SWARMS = [TEST_SWARMS[x] for x in range(len(TEST_SWARMS)) if x not in remove_swarm_ind]
			flag = any(flag_list)
		else:
			flag = False

	return TEST_SWARMS


def get_swarms(DF, T0, config):

	lat0 = DF.Latitude.mean()
	lon0 = DF.Longitude.mean()
	ZN_LET = utm.latitude_to_zone_letter(lat0)
	ZN_NUM = utm.latlon_to_zone_number(lat0,lon0)

	east, north, ignore1, ignore2 = utm.from_latlon(DF.Latitude, DF.Longitude, force_zone_number=ZN_NUM, force_zone_letter=ZN_LET)
	DF['x'] = east/1000
	DF['y'] = north/1000

	SWARMS = []
	for params in config.swarm_parameters:
		# scale time to match distance
		cat_df = DF.copy()[DF['Time'] > (T0 - params['MAX_EVT_TIME']).strftime('%Y-%m-%d %H:%M:%S')]
		if len(cat_df) == 0:
			continue
		t = cat_df.Time
		dtime = np.array([(t0-t.min()).total_seconds() for t0 in t])
		dtime = dtime * (params['MAX_EVT_DISTANCE'] / float(params['MAX_EVT_TIME']))
		# put distance and time together
		X = np.array([cat_df['x'], cat_df['y'], dtime]).T
		# X = np.array([cat_df['x'], cat_df['y'], cat_df['Depth'], dtime]).T
		db = DBSCAN(eps=params['MAX_EVT_DISTANCE'], min_samples=params['MIN_NUM_EVT']).fit(X)


		cat_df.loc[:,'label'] = db.labels_
		cat_df.loc[:,'param_duration'] = float(params['MAX_EVT_TIME'])
		ALL_DETECTS = cat_df[cat_df['label']>-1]
		# NOISE = cat_df[cat_df['label']==-1]

		for i in ALL_DETECTS.label.unique():
			df = cat_df[cat_df['label']==i]
			SWARMS.append(df.copy())

	return SWARMS


def addPhaseHint(cat):
	for eq in cat:
		# Loop over catalog
		for pick in eq.picks:
			# Loop over picks
			# Go get phase hint
			nowPickID = pick.resource_id
			for arrival in eq.preferred_origin().arrivals:
				nowArrID = arrival.pick_id
				if nowPickID == nowArrID:
					pick.phase_hint=arrival.phase
	return cat


def download_events(T0, config):
	
	T2 = T0
	T1 = T2 - config.DURATION

	ENDTIME = T2.strftime('%Y-%m-%dT%H:%M:%S')
	STARTTIME = T1.strftime('%Y-%m-%dT%H:%M:%S')
	# URL='{}starttime={}&endtime={}&minmagnitude={}&maxdepth={}&includearrivals=true&format=xml'.format(os.environ['GUGUAN_URL'],
	# 																								   STARTTIME,
	# 																								   ENDTIME,
	# 																								   config.MAGMIN,
	# 																								   config.MAXDEP)
	URL='{}starttime={}&endtime={}&maxdepth={}&includearrivals=true&format=xml'.format(os.environ['GUGUAN_URL'],
																									   STARTTIME,
																									   ENDTIME,
																									   config.MAXDEP)
	buffer = BytesIO()
	c = pycurl.Curl()
	c.setopt(c.URL, URL) #initializing the request URL
	c.setopt(c.WRITEDATA, buffer) #setting options for cURL transfer  
	c.setopt(c.SSL_VERIFYPEER, 0) #setting the file name holding the certificates
	c.setopt(c.SSL_VERIFYHOST, 0) #setting the file name holding the certificates

	attempt = 1
	while attempt <= 3:
		try:
			c.perform() # perform file transfer
			c.close() #Ending the session and freeing the resources
			body = buffer.getvalue()
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


def catalog_to_dataframe(CAT, VOLCS):

	LATS = []
	LONS = []
	DEPS = []
	MAGS = []
	TIME = []
	ID   = []
	RMS  = []
	AZ_GAP = []
	V_DIST = []
	VOLCANO = []

	for eq in CAT:
		LATS.append(eq.preferred_origin().latitude)
		LONS.append(eq.preferred_origin().longitude)
		DEPS.append(eq.preferred_origin().depth/1000)
		TIME.append(eq.preferred_origin().time.datetime)
		try:
			RMS.append(eq.preferred_origin().quality.standard_error)
		except:
			RMS.append(1e2)
		try:
			AZ_GAP.append(eq.preferred_origin().quality.azimuthal_gap)
		except:
			AZ_GAP.append(360)
		if eq.preferred_magnitude():
			MAGS.append(eq.preferred_magnitude().mag)
		else:
			MAGS.append(np.nan)
		evid = eq.resource_id.id
		ID.append(evid)

		volcs = utils.volcano_distance(eq.preferred_origin().longitude, eq.preferred_origin().latitude, VOLCS)
		volcs = volcs.sort_values('distance')
		V_DIST.append(volcs.iloc[0].distance)
		VOLCANO.append(volcs.iloc[0].Volcano)

	cat_df = pd.DataFrame({'Time': TIME, 'Latitude':LATS, 'Longitude':LONS, 'Depth':DEPS, 'Magnitude':MAGS, 'ID':ID, 'V_DIST':V_DIST, 'VOLCANO':VOLCANO})
	cat_df['Time'] = pd.to_datetime(cat_df['Time'])

	return cat_df