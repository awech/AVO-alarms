import os
import sys
import pandas as pd
import numpy as np
from obspy import Catalog, UTCDateTime, Stream
from obspy.geodetics.base import gps2dist_azimuth
import cartopy
from cartopy.io.img_tiles import GoogleTiles
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
from matplotlib.ticker import FormatStrFormatter
import matplotlib.pyplot as plt
from matplotlib.dates import date2num
import matplotlib as m
from matplotlib.path import Path
import shapely.geometry as sgeom
import warnings
import traceback
import time
from obspy.clients.fdsn import Client
from pathlib import Path

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils import messaging, plotting, processing


warnings.filterwarnings("ignore")

attempt = 1
while attempt <= 3:
    try:
        client = Client('IRIS')
        break
    except:
        time.sleep(2)
        attempt+=1
        client = None

def run_alarm(config, T0, test=False):

    # Download the event data
    print(T0.strftime('%Y-%m-%d %H:%M'))
    print('Downloading events...')
    T2 = T0
    T1 = T2 - config.DURATION
    URL = '{}starttime={}&endtime={}&minmagnitude={}&maxdepth={}&includearrivals=true&format=xml'.format(os.environ['GUGUAN_URL'],
                                                                                                         T1.strftime('%Y-%m-%dT%H:%M:%S'),
                                                                                                         T2.strftime('%Y-%m-%dT%H:%M:%S'),
                                                                                                         config.MAGMIN,
                                                                                                         config.MAXDEP)
    CAT = processing.download_hypocenters(URL)

    # Error pulling events
    if CAT is None:
        state = 'WARNING'
        state_message = '{} (UTC) FDSN connection error'.format(T0.strftime('%Y-%m-%d %H:%M'))
        messaging.icinga(config, state, state_message)
        return

    # No events
    if len(CAT) == 0:
        state = 'OK'
        state_message = '{} (UTC) No new earthquakes'.format(T0.strftime('%Y-%m-%d %H:%M'))
        messaging.icinga(config, state, state_message)
        return

    # Compare new event distance with volcanoes
    VOLCS = pd.read_excel(config.volc_file)
    CAT_DF = catalog_to_dataframe(CAT, VOLCS)
    CAT_DF = CAT_DF[CAT_DF['V_DIST']<config.DISTANCE]

    # New events, but not close enough to volcanoes
    if len(CAT_DF) == 0:
        print('Earthquakes detected, but not near any volcanoes')
        state = 'OK'
        state_message = '{} (UTC) No new earthquakes'.format(T0.strftime('%Y-%m-%d %H:%M'))
        messaging.icinga(config, state, state_message)
        return

    # Read in old events. Write all recent events. Filter to new events
    OLD_EVENTS = pd.read_csv(config.outfile) 
    CAT_DF[['ID']].to_csv(config.outfile, index=False)
    NEW_EVENTS=CAT_DF[~CAT_DF['ID'].isin(OLD_EVENTS.ID)]
    NEW_EVENTS = NEW_EVENTS.sort_values('Time')
    
    # No new events to process
    if len(NEW_EVENTS) == 0:
        print('Earthquakes detected, but already processed in previous run')
        state = 'WARNING'
        state_message = '{} (UTC) Old event detected'.format(T0.strftime('%Y-%m-%d %H:%M'))
        messaging.icinga(config, state, state_message)
        return

    print('{} new events found. Looping through events...'.format(len(NEW_EVENTS)))
    # Filter Obspy catalog to new events near volcanoes
    CAT_NEW = Catalog()
    for i, row in NEW_EVENTS.iterrows():
        filter1 = "time >= {}".format(row.Time.strftime('%Y-%m-%dT%H:%M:%S.%f'))
        filter2 = "time <= {}".format(row.Time.strftime('%Y-%m-%dT%H:%M:%S.%f'))
        CAT_NEW.append(CAT.filter(filter1, filter2)[0])

    # Add phase info to new events
    try:
        CAT_NEW = addPhaseHint(CAT_NEW)
    except:
        print('Could not add phase type...')

    for eq in CAT_NEW:
        print('Processing {}, {}'.format(eq.short_str(), eq.resource_id.id))
        volcs = processing.volcano_distance(eq.preferred_origin().longitude, eq.preferred_origin().latitude, VOLCS)
        volcs = volcs.sort_values('distance')
    
        #### Generate Figure ####
        try:
            attachment = plot_event(eq, volcs, config)
            new_filename = '{}/{}_M{:.1f}_{}.png'.format(os.environ['TMP_FIGURE_DIR'],
                                                 eq.preferred_origin().time.strftime('%Y%m%dT%H%M%S'),
                                                 eq.preferred_magnitude().mag,
                                                 ''.join(eq.resource_id.id.split('/')[-2:]).lower())
            os.rename(attachment, new_filename)
            attachment = new_filename
        except:
            attachment = []
            print('Problem making figure. Continue anyway')
            b = traceback.format_exc()
            err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
            print(err_message)


        # craft and send the message
        subject, message = create_message(eq, volcs)

        print('Sending message...')
        # messaging.send_alert(config.alarm_name, subject, message, attachment)
        print('Posting to mattermost...')
        messaging.post_mattermost(config, subject, message, filename=attachment)

        # Post to dedicated response channels for volcnoes listed in config file
        if 'mm_response_channels' in dir(config):
            if volcs.iloc[0].Volcano in config.mm_response_channels.keys():
                config.mattermost_channel_id = config.mm_response_channels[volcs.iloc[0].Volcano]
                messaging.post_mattermost(config, subject, message, filename=attachment)

        # delete the file you just sent
        if attachment:
            os.remove(attachment)

        state = 'CRITICAL'
        state_message = '{} (UTC) {}'.format(eq.preferred_origin().time.strftime('%Y-%m-%d %H:%M:%S'), subject)
    
    messaging.icinga(config, state, state_message)

    return


def create_message(eq, volcs):
    origin=eq.preferred_origin()
    t = pd.Timestamp(origin.time.datetime, tz='UTC')
    t_local = t.tz_convert(os.environ['TIMEZONE'])
    Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M:%S'), t_local.tzname())

    message = '{} UTC\n{}'.format(t.strftime('%Y-%m-%d %H:%M:%S'), Local_time_text)
    message = '{}\n\n**Magnitude:** {:.1f}'.format(message, eq.preferred_magnitude().mag)
    message = '{}\n**Latitude:** {:.3f}\n**Longitude:** {:.3f}'.format(message, origin.latitude, origin.longitude)
    message = '{}\n**Depth:** {:.1f} km'.format(message, origin.depth/1000)
    message = '{}\n**Event ID:** {}'.format(message, ''.join(eq.resource_id.id.split('/')[-2:]).lower())
    
    volcs = volcs.sort_values('distance')
    v_text = ''
    for i, row in volcs[:3].iterrows():
        v_text = '{}{} ({:.0f} km), '.format(v_text, row.Volcano, row.distance)
    v_text = v_text.replace('_',' ')
    message = '{}\n**Nearest volcanoes:** {}'.format(message, v_text[:-2])
    
    try:
        message = '{}\n\n***--- {} Location ---***'.format(message, origin.evaluation_mode.replace('manual','reviewed').upper())
        message = '{}\nUsing {:g} phases from {:g} stations'.format(message, origin.quality.used_phase_count, origin.quality.used_station_count)
        message = '{}\n**Azimuthal Gap:** {:g} degrees'.format(message, origin.quality.azimuthal_gap)
        message = '{}\n**Standard Error:** {:g} s'.format(message, origin.quality.standard_error)
        message = '{}\n**Vertical/Horizontal Error:** {:.1f} km / {:.1f} km'.format(message, origin.depth_errors['uncertainty']/1000, origin.origin_uncertainty.horizontal_uncertainty/1000.)
    except:
        pass

    subject = 'M{:.1f} earthquake at {}'.format(eq.preferred_magnitude().mag, volcs.iloc[0].Volcano)

    return subject, message


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

        volcs = processing.volcano_distance(eq.preferred_origin().longitude, eq.preferred_origin().latitude, VOLCS)
        volcs = volcs.sort_values('distance')
        V_DIST.append(volcs.iloc[0].distance)

    cat_df = pd.DataFrame({'Time': TIME, 'Latitude':LATS, 'Longitude':LONS, 'Depth':DEPS, 'Magnitude':MAGS, 'ID':ID, 'V_DIST':V_DIST})
    cat_df['Time'] = pd.to_datetime(cat_df['Time'])

    return cat_df


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


def get_channels(eq):

    NS   = []
    NSLC = []
    SCNL = []
    LATS = []
    LONS = []
    DIST = []
    P    = []
    S    = []
    for p in eq.picks:
        wid=p.waveform_id
        net, sta, loc, chan = wid.id.split('.')
        ns = '.'.join([net,sta])
        if (ns not in NS):
            print('Getting lat/lon info for {}'.format(wid.id))
            inventory = client.get_stations(network=net,
                                            station=sta,
                                            location=loc,
                                            channel=chan)
            # NSLC.append(wid.id.replace('..','.--.'))
            NS.append(ns)
            NSLC.append(wid.id)
            SCNL.append('.'.join([sta, chan, net, loc]))
            LATS.append(inventory[0][0].latitude)
            LONS.append(inventory[0][0].longitude)
    for i, nslc in enumerate(NSLC):
        dist = gps2dist_azimuth(eq.preferred_origin().latitude, eq.preferred_origin().longitude, LATS[i], LONS[i])[0]/1000.
        DIST.append(dist)

    STAS = pd.DataFrame({'NS':NS, 'NSLC':NSLC, 'SCNL':SCNL, 'Latitude':LATS, 'Longitude':LONS, 'Distance':DIST})

    STAS['P'] = np.nan
    STAS['S'] = np.nan
    for p in eq.picks:
        ns = '.'.join(p.waveform_id.id.split('.')[:2])
        STAS.loc[STAS.NS==ns, p.phase_hint] = p.time

    STAS = STAS.sort_values('Distance')

    return STAS


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


def plot_event(eq, volcs, config):
    m.use('Agg')
    n_blank = 4

    ################### Download data ###################
    channels = get_channels(eq)
    plot_chans = channels[:8]
    st = processing.grab_data(list(plot_chans.SCNL.values), 
                        eq.preferred_origin().time-20, 
                        eq.preferred_origin().time+50)
    try:
        client._attach_responses(st)
        st.remove_response()
        velocity=True
    except:
        velocity=False

    print('Plotting traces...')
    st.trim(st[0].stats.starttime+5, st[0].stats.endtime-5)
    st.detrend()
    ST = Stream()
    for k in np.arange(n_blank):
        ST+=st[0]
    ST+=st
    fig = plt.figure(figsize=(4,9))
    h = ST.plot(fig=fig, equal_scale=False, automerge=False, linewidth=0.5)
    for i, ax in enumerate(h.get_axes()):
        if i >= n_blank:
            ax.grid(axis='x', linewidth=0.2, linestyle='--')
            y0 = ax.get_ylim()[1]*0.5
            try:
                ax.plot(np.ones(2)*date2num(plot_chans.iloc[i-n_blank].P.datetime), [-y0, y0], color='r', linewidth=1)
            except:
                ax.plot(np.ones(2)*np.nan, [-y0, y0], color='r', linewidth=1)
            try:
                ax.plot(np.ones(2)*date2num(plot_chans.iloc[i-n_blank].S.datetime), [-y0, y0], color='dodgerblue', linewidth=1)
            except:
                ax.plot(np.ones(2)*np.nan, [-y0, y0], color='dodgerblue', linewidth=1)
            if velocity:
                tr = st[i-n_blank]
                peak_num = np.abs(tr.data).max()
                if np.log10(peak_num) < -6:
                    tmp_str = '{:.1f}\n'.format(peak_num*1e9) + r'$nm/s$'
                    label_color = 'black'
                    fw = 'normal'
                elif np.log10(peak_num) < -3:
                    tmp_str = '{:.1f}\n'.format(peak_num*1e6) + r'$\mu$' + r'$m/s$'
                    label_color = 'black'
                    fw = 'normal'
                elif np.log10(peak_num) < 0:
                    tmp_str = '{:.2f}\n'.format(peak_num*1e3) + r'$mm/s$'
                    label_color = 'firebrick'
                    fw = 'bold'
                ax.text(ax.get_xlim()[0]-1/86400, tr.data[0], tmp_str, 
                                                              fontsize=6, 
                                                              horizontalalignment='center', 
                                                              verticalalignment='bottom', 
                                                              rotation_mode='anchor', 
                                                              rotation=90,
                                                              color=label_color,
                                                              fontweight=fw)
    x_labels = ax.get_xticklabels()
    x_labels[0].set_text(UTCDateTime(x_labels[0].get_text()).strftime('%H:%M:%S'))
    ax.set_xticklabels(x_labels)
    for i, ax in enumerate(h.get_axes()):
        if i < n_blank:
            h.delaxes(ax)
        else:
            ax.get_yaxis().set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['top'].set_visible(False)
            ax.spines['left'].set_visible(False)
            ax.spines['right'].set_visible(False)
            v = ax.get_children()[1] # get_children()[3] for python3.7
            label = v.get_text()
            ax.text(0.01, 0.7, label, fontsize=6, transform=ax.transAxes, bbox=dict(boxstyle="round", fc="w", ec="w", alpha=0.8, linewidth=0))
            v.remove()
    ax.tick_params('x',length=0)



    #################### Add main map ####################
    grid = plt.GridSpec(len(ST), 1, wspace=0.05, hspace=0.6)
    print('Plotting main map...')
    extent = get_extent(volcs.iloc[0].Latitude, volcs.iloc[0].Longitude, dist=25)
            # CRS = cartopy.crs.Mercator(central_longitude=np.mean(extent[:2]), min_latitude=extent[2], max_latitude=extent[3], globe=None)
            # ax1 = plt.subplot(grid[:n_blank,0], projection=CRS)
            # ax1.set_extent(extent,cartopy.crs.PlateCarree())
            # coast = cartopy.feature.GSHHSFeature(scale="high", rasterized=True)
            # ax1.add_feature(coast, facecolor="lightgray", linewidth=0.5)
            # water_col=tuple(np.array([165,213,229])/255.)
            # ax1.set_facecolor(water_col)
            # ax1.background_patch.set_facecolor(water_col)
    ax1 = plt.subplot(grid[:n_blank,0], projection=ShadedReliefESRI().crs)
    ax1.set_extent(extent)
    ax1.add_image(ShadedReliefESRI(), 11)
    lon_grid = [np.mean(extent[:2])-np.diff(extent[:2])[0]/4, np.mean(extent[:2])+np.diff(extent[:2])[0]/4]
    lat_grid = [np.mean(extent[-2:])-np.diff(extent[-2:])[0]/4, np.mean(extent[-2:])+np.diff(extent[-2:])[0]/4]
    # gl = ax1.gridlines(draw_labels={"bottom": "x", "right": "y"},
    # 				   xlocs=lon_grid, ylocs=lat_grid,
    # 				   xformatter=LongitudeFormatter(number_format='.2f', direction_label=False),
    # 				   yformatter=LatitudeFormatter(number_format='.2f', direction_label=False),
    # 				   alpha=0.2, 
    # 				   color='gray', 
    # 				   linewidth=0.5,
    # 				   xlabel_style={'fontsize':6},
    # 				   ylabel_style={'fontsize':6})
    gl = ax1.gridlines(draw_labels=True, xlocs=lon_grid, ylocs=lat_grid,
                       alpha=0.0, 
                       color='gray', 
                       linewidth=0.5)
    gl.xlabels_top = False
    gl.ylabels_left = False
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER
    gl.xlabel_style = {'size': 6}
    gl.ylabel_style = {'size': 6}

    ax1.plot(volcs[:10].Longitude, volcs[:10].Latitude, '^', markerfacecolor='g', markersize=8, markeredgecolor='k', markeredgewidth=0.5, transform=cartopy.crs.PlateCarree())
    ax1.plot(channels.Longitude, channels.Latitude, 's', markerfacecolor='orange', markersize=5, markeredgecolor='k', markeredgewidth=0.4, transform=cartopy.crs.PlateCarree())
    ax1.plot(eq.preferred_origin().longitude, eq.preferred_origin().latitude, 'o', markerfacecolor='firebrick', markersize=8, markeredgecolor='k', markeredgewidth=0.7, transform=cartopy.crs.PlateCarree())
    for i, row in channels.iterrows():
        t = ax1.text(row.Longitude+0.006, row.Latitude+0.006, row.NS.split('.')[-1], clip_on=True, fontsize=6, transform=cartopy.crs.PlateCarree())
        t.clipbox = ax1.bbox
    
    ax1.set_title('{}\nM{:.1f}, {:.1f} km from {}\nDepth: {:.1f} km'.format(eq.preferred_origin().time.strftime('%Y-%m-%d %H:%M:%S'),
                                                               eq.preferred_magnitude().mag, 
                                                               volcs.iloc[0].distance,
                                                               volcs.iloc[0].Volcano,
                                                               eq.preferred_origin().depth/1000,
                                                               ),
                  fontsize=8)

    fig.subplots_adjust(top=0.94)
    fig.subplots_adjust(bottom=0.03)


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

    print('Saving figure...')
    jpg_file = plotting.save_file(fig, config, dpi=250)
    plt.close(fig)

    return jpg_file