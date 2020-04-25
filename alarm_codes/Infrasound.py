# Airwave alarm to be run on set of channels in small aperture infrasound array
# Based on MATLAB code originally written by Matt Haney and John Lyons
#
# Wech 2017-06-08

from . import utils
from obspy import UTCDateTime, Stream
from obspy.core.util import AttribDict
from obspy.geodetics.base import gps2dist_azimuth
from obspy.signal.cross_correlation import correlate, xcorr_max
from itertools import combinations
import numpy as np
import os
from pandas import DataFrame, Timestamp
import time
import matplotlib as m
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.dates as mdates


# main function called by alarm.py
def run_alarm(config,T0):

    time.sleep(config.latency)
    state_message='{} (UTC) {}'.format(T0.strftime('%Y-%m-%d %H:%M'),config.alarm_name)

    #### download data ####
    SCNL=DataFrame.from_dict(config.SCNL)
    t1 = T0-config.duration
    t2 = T0
    st = utils.grab_data(SCNL['scnl'].tolist(),t1,t2,fill_value=0)
    st = add_coordinate_info(st,SCNL)
    ########################

    #### check for enough data ####
    for tr in st:
        if np.sum(np.abs(np.abs(tr.data)))==0:
            st.remove(tr)
    if len(st)<config.min_chan:
        state_message='{} - Not enough channels!'.format(state_message)
        state='WARNING'
        utils.icinga_state(config,state,state_message)
        return
    ########################

    #### check for gappy data ####
    for tr in st:
        num_zeros=len(np.where(tr.data==0)[0])
        if num_zeros/float(tr.stats.npts)>0.01:
            st.remove(tr)
    if len(st)<config.min_chan:
        state_message='{} - Gappy data!'.format(state_message)
        state='WARNING'
        utils.icinga_state(config,state,state_message)
        return
    ########################

    #### preprocess data ####
    st.detrend('demean')
    st.taper(max_percentage=None,max_length=config.taper_val)
    st.filter('bandpass',freqmin=config.f1,freqmax=config.f2)
    for tr in st:
        if tr.stats['sampling_rate']==100:
            tr.decimate(2)
        if tr.stats['sampling_rate']!=50:
            tr.resample(50.0)
    ########################

    #### check amplitude threshold ####
    min_pa=np.array([v['min_pa'] for v in config.VOLCANO]).min()
    st=Stream([tr for tr in st if np.any(np.abs(tr.data*config.digouti)>min_pa)])
    if len(st)<config.min_chan:
        state_message='{} - not enough channels exceeding amplitude threshold!'.format(state_message)
        state='OK'
        utils.icinga_state(config,state,state_message)
        return
    ########################


    #### Set up grid ####
    config    = get_volcano_backazimuth(st,config)
    yx, intsd, ints_az = setup_coordinate_system(st)
    #### Cross correlate ####
    lags, lags_inds1, lags_inds2 = calc_triggers(st,config,intsd)
    cmbm2, cmbm2n, counter, mpk = associator(lags_inds1,lags_inds2,st,config)

    if counter == 0:
        state_message='{} - alarm normal.'.format(state_message)
        state='OK'
    else:
        #### some event detected...determine velocity and azimuth ####
        velocity, azimuth, rms = inversion(cmbm2n,cmbm2,intsd,ints_az,lags_inds1,lags_inds2,lags,mpk)
        d_Azimuth    = azimuth - np.array([t['back_azimuth'] for t in config.VOLCANO])
        az_tolerance = np.array([t['Azimuth_tolerance'] for t in config.VOLCANO])
        #### check if this is airwave velocity from a volcano in config file list ####
        if np.any(np.abs(d_Azimuth) < az_tolerance):
            v_ind=np.argmax(np.abs(d_Azimuth) < az_tolerance)
            mx_pressure=np.max(np.array([np.max(np.abs(tr.data)) for tr in st]))*config.digouti
            if config.VOLCANO[v_ind]['vmin'] < velocity < config.VOLCANO[v_ind]['vmax'] and mx_pressure > config.VOLCANO[v_ind]['min_pa']:
                #### DETECTION ####
                volcano=config.VOLCANO[v_ind]
                d_Azimuth=d_Azimuth[v_ind]
                
                print('Airwave Detection!!!')
                state_message='{} - {} detection! {:.1f} Pa peak pressure'.format(state_message,volcano['volcano'],mx_pressure)
                state='CRITICAL'

            else:
                print('Non-volcano detect!!!')
                state_message='{} - Detection with wrong velocity ({:.1f} km/s) or maximum pressure ({:.1f} Pa)'.format(state_message,velocity,mx_pressure)
                state='WARNING'
        else:
            #### trigger, but not from volcano ####
            print('Non-volcano detect!!!')
            state_message='{} - Detection with wrong backazimuth ({:.0f} from N)'.format(state_message,azimuth)
            state='WARNING'

    if state=='CRITICAL':
        #### Generate Figure ####
        filename=make_figure(st,volcano,T0,config,mx_pressure)
        # try:
        #     filename=make_figure(st,volcano,T0,config,mx_pressure)
        # except:
        #     filename=None
        
        ### Craft message text ####
        subject, message = create_message(t1,t2,config,volcano,azimuth,d_Azimuth,velocity,mx_pressure)

        ### Send message ###
        utils.send_alert(config.alarm_name,subject,message,filename)
        utils.post_mattermost(config,subject,message,filename)
        # delete the file you just sent
        if filename:
            os.remove(filename)

    # send heartbeat status message to icinga
    utils.icinga_state(config,state,state_message)


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
        tmp_lat=SCNL[SCNL['scnl']==tmp_scnl].sta_lat.values[0]
        tmp_lon=SCNL[SCNL['scnl']==tmp_scnl].sta_lon.values[0]
        tr.stats.coordinates=AttribDict({
                                'latitude': tmp_lat,
                                'longitude': tmp_lon,
                                'elevation': 0.0})
    return st

def get_volcano_backazimuth(st, config):
    lon0 = np.mean([tr.stats.coordinates.longitude for tr in st])
    lat0 = np.mean([tr.stats.coordinates.latitude for tr in st])
    for volc in config.VOLCANO:
        if "back_azimuth" not in volc:
            tmp = gps2dist_azimuth(lat0, lon0, volc["v_lat"], volc["v_lon"])
            volc["back_azimuth"] = tmp[1]
    return config


def setup_coordinate_system(st):
    R = 6372.7976   # radius of the earth
    lons  = np.array([tr.stats.coordinates.longitude for tr in st])
    lats  = np.array([tr.stats.coordinates.latitude for tr in st])
    lon0  = lons.mean()*np.pi/180.0
    lat0  = lats.mean()*np.pi/180.0
    yx    = R*np.array([ lats*np.pi/180.0-lat0, (lons*np.pi/180.0-lon0)*np.cos(lat0) ]).T
    intsd = np.zeros([len(lons),len(lons)])
    ints_az= np.zeros([len(lons),len(lons)])
    for ii in range(len(st[:-1])):
        for jj in range(ii+1,len(st)):
            # intsd[i,j]=np.sqrt(np.square(yx[j][0]-yx[i][0])+np.square(yx[j][1]-yx[i][1]))
            tmp=gps2dist_azimuth(lats[ii],lons[ii],lats[jj],lons[jj])
            intsd[ii,jj]=tmp[0]
            ints_az[ii,jj]=tmp[1]

    return yx, intsd, ints_az

def calc_triggers(st,config,intsd):
    lags       = np.array([])
    lags_inds1 = np.array([])
    lags_inds2 = np.array([])
    #### cross correlate all station pairs ####
    for ii in range(len(st[:-1])):
        for jj in range(ii + 1, len(st)):
            cc_vector = correlate(
                st[ii].data, st[jj].data, config.cc_shift_length
            )
            index, value = xcorr_max(cc_vector)
            #### if best xcorr value is negative, find the best positive one ####
            if value < 0:
                index = cc_vector.argmax() - config.cc_shift_length
                value = cc_vector.max()
            dt = index / st[0].stats.sampling_rate
            #### check that the best lag is at least the vmin value
            #### and check for minimum cross correlation value
            all_vmin = np.array([v["vmin"] for v in config.VOLCANO]).min()
            if np.abs(dt) < intsd[ii, jj] / all_vmin and value > config.min_cc:
                lags = np.append(lags, dt)
                lags_inds1 = np.append(lags_inds1, ii)
                lags_inds2 = np.append(lags_inds2, jj)

    #### return lag times, and
    return lags, lags_inds1, lags_inds2

def associator(lags_inds1,lags_inds2,st,config):
    #### successively try to associate, starting with all stations
    #### and quit at config.min_sta

    counter   = 0
    mpk = len(st)

    while counter==0 and mpk>=config.min_chan:
        cmbm = np.array(list(combinations(range(0,len(st)),mpk)))
        cntr = len(cmbm)
        # find how many relevant picks exist for all combinations of delay times
        ncntrm = np.zeros((mpk,mpk,cntr))

        for jj,trig in enumerate(lags_inds1):
            for ii in range(0,cntr):
                if np.sum(lags_inds1[jj] == cmbm[ii,]) == 1 and np.sum(lags_inds2[jj] == cmbm[ii,]) == 1:
                    ind1=(lags_inds1[jj] == cmbm[ii,]).argmax()
                    ind2=(lags_inds2[jj] == cmbm[ii,]).argmax()
                    ncntrm[ind1,ind2,ii] = 1

        # if one of the row/column sums is at least 3, accept it
        cmbm2  = np.zeros((cntr,mpk))
        cmbm2n = np.zeros(cntr)

        for ii in range(cntr):
            if np.sum(np.sum(ncntrm[:,:,ii],1) == 0) == 1:
                cmbm2[counter,:] = cmbm[ii,:]
                # total number of qualifying picks
                cmbm2n[counter] = np.sum(np.sum(ncntrm[:,:,ii],1))
                counter = counter + 1
        # if no matches, decrement and try again
        if counter==0:
            mpk = mpk -1
    
    cmbm2 = cmbm2.astype('int')
    cmbm2n = cmbm2n.astype('int')

    return cmbm2, cmbm2n, counter, mpk

def inversion(cmbm2n,cmbm2,intsd,ints_az,lags_inds1,lags_inds2,lags,mpk):
    # for jj in range(counter):
    jj=0
    # the size of the dt and Dm3
    dt  = np.zeros(cmbm2n[jj])
    Dm3 = np.zeros((cmbm2n[jj],2))

    # initialize interstation distance and azimuth vectors
    ds = np.array([])
    az = np.array([])

    # grab interstation distance and azimuth for all pairs in this tuple
    for num,kk in enumerate(cmbm2[jj,range(0,mpk-1)]):
        for ii in cmbm2[jj,range(num+1,mpk)]:
            ds = np.append(ds,intsd[kk,ii])
            az = np.append(az,ints_az[kk,ii])

    # some counters to find if there is a match in the trgs vector
    mtrxc = 0
    dacnt = 0

    # all 5 may not exist
    for kk in range(0,mpk-1):
        for ii in range(kk+1,mpk):
            tmp=np.array([lags_inds1,lags_inds2]).T - np.repeat(np.array([cmbm2[jj,kk],cmbm2[jj,ii]],ndmin=2),len(lags_inds1),0)
            tmp=np.sum(np.abs(tmp),1)
            mmin = tmp.min()
            mloc = tmp.argmin()
            if mmin==0:
                dt[mtrxc] = lags[mloc]
                Dm3[mtrxc,:] = [ds[dacnt]*np.cos(az[dacnt]*(np.pi/180.0)) , ds[dacnt]*np.sin(az[dacnt]*(np.pi/180.0))]
                mtrxc=mtrxc+1
            dacnt=dacnt+1
    Dm3=Dm3/1000.0  # convert to kilometers

    # generalized inverse of slowness matrix
    Gmi = np.linalg.inv(np.matmul(Dm3.T,Dm3))
    # slowness - least squares
    sv = np.matmul(np.matmul(Gmi,Dm3.T),dt.T)
    # velocity from slowness
    velocity = 1/np.sqrt(np.square(sv[0])+np.square(sv[1]))
    # cosine and sine for backazimuth
    caz3 = velocity*sv[0]
    saz3 = velocity*sv[1]
    # 180 degree resolved backazimuth to source
    azimuth = np.arctan2(saz3,caz3)*(180/np.pi)
    if azimuth<0:
        azimuth=azimuth+360
    # rms
    rms = np.sqrt(np.mean(np.square(np.matmul(Dm3,sv)-dt.T)))

    return velocity, azimuth, rms

def make_figure(st,volcano,T0,config,mx_pressure):
    m.use('Agg')

    infrasound_plot_duration=600
    seismic_plot_duration=3600
    if hasattr(config,'infrasound_plot_duration'):
        infrasound_plot_duration=config.infrasound_plot_duration
    if hasattr(config,'seismic_plot_duration'):
        seismic_plot_duration=config.seismic_plot_duration


    start = time.time()
    ##### get seismic data #####
    seis = utils.grab_data(volcano['seismic_scnl'],T0-seismic_plot_duration, T0,fill_value='interpolate')
    ##### get infrasound data #####
    infra_scnl = ['{}.{}.{}.{}'.format(tr.stats.station,tr.stats.channel,tr.stats.network,tr.stats.location) for tr in st]
    infra = utils.grab_data(infra_scnl,T0-infrasound_plot_duration, T0,fill_value='interpolate')
    end = time.time()
    print('{:.2f} seconds to grab figure data.'.format(end - start))


    ###################################################
    ################# plot infrasound #################

    #### preprocess data ####
    infra.detrend('demean')
    infra.taper(max_percentage=None,max_length=config.taper_val)
    infra.filter('bandpass',freqmin=config.f1,freqmax=config.f2)
    [tr.decimate(2,no_filter=True) for tr in infra if tr.stats.sampling_rate==100]
    [tr.decimate(2,no_filter=True) for tr in infra if tr.stats.sampling_rate==50]
    [tr.resample(25) for tr in infra if tr.stats.sampling_rate!=25]

    ##### stack infrasound data #####
    print('stacking infrasound data')
    stack=xcorr_align_stream(infra,config)

    ##### plot stack spectrogram #####
    plt.figure(figsize=(4.5,4.5))
    colors=cm.jet(np.linspace(-1,1.2,256))
    color_map = LinearSegmentedColormap.from_list('Upper Half', colors)

    ax=plt.subplot(len(seis)+3,1,1)
    ax.set_title(config.alarm_name+' Alarm: '+volcano['volcano']+ ' detection!')
    print(np.max(stack.data))
    stack.spectrogram(title='',log=False,samp_rate=25,dbscale=True,per_lap=0.7,mult=25.0,wlen=3,cmap=color_map,axes=ax)
    ax.set_yticks([3,6,9,12])
    ax.set_ylim(0,12.5)
    ax.set_ylabel(stack.stats.station+'\nstack',fontsize=5,
                                         rotation='horizontal',
                                         multialignment='center',
                                         horizontalalignment='right',
                                         verticalalignment='center')
    ax.yaxis.set_ticks_position('right')
    ax.tick_params('y',labelsize=4)
    ax.set_xticks([])

    ##### plot stack trace #####
    ax=plt.subplot(len(seis)+3,1,2)
    t1=mdates.date2num(infra[0].stats.starttime.datetime)
    # round to nearest minute
    t1=round(t1*24*60)/(24*60)
    t2=mdates.date2num(infra[0].stats.endtime.datetime)
    # round to nearest minute
    t2=round(t2*24*60)/(24*60)
    t_vector=np.linspace(t1,t2,stack.stats.npts)
    plt.plot(t_vector,stack.data,color='k',LineWidth=0.2)
    ax.set_ylabel(stack.stats.station+'\nstack',fontsize=5,
                                         rotation='horizontal',
                                         multialignment='center',
                                         horizontalalignment='right',
                                         verticalalignment='center')
    ax.yaxis.set_ticks_position('right')
    ax.tick_params('y',labelsize=4)
    ax.set_xlim(t1,t2)
    infra_tick_fmt='%H:%M'
    if infrasound_plot_duration in [1800,3600,5400,7200]:
        n_infra_ticks=7
    elif infrasound_plot_duration in [300,600,900,1200,1500,2100,2400,2700,3000,3300]:
        n_infra_ticks=6
    else:
        n_infra_ticks=6
        infra_tick_fmt='%H:%M:%S'

    t_ticks=np.linspace(t1,t2,n_infra_ticks)
    ax.set_xticks(t_ticks)
    ax.set_xticklabels([mdates.num2date(t).strftime(infra_tick_fmt) for t in t_ticks])
    ax.tick_params('x',labelsize=5)
    ax.set_xlabel('{:.0f} Minute Infrasound Stack\n{} UTC,   Peak Pressure: {:.1f} Pa'.format(round((t2-t1)*24*60),
                                                        infra[0].stats.starttime.strftime('%Y-%b-%d'),
                                                        mx_pressure))
    ###################################################
    ###################################################


    ###################################################
    ################## plot seismic ###################

    #### preprocess data ####
    seis.detrend('demean')
    [tr.decimate(2,no_filter=True) for tr in seis if tr.stats.sampling_rate==100]
    [tr.decimate(2,no_filter=True) for tr in seis if tr.stats.sampling_rate==50]
    [tr.resample(25) for tr in seis if tr.stats.sampling_rate!=25]

    seis_tick_fmt='%H:%M'
    if seismic_plot_duration in [1800,3600,5400,7200]:
        n_seis_ticks=7
    elif seismic_plot_duration in [300,600,900,1200,1500,2100,2400,2700,3000,3300]:
        n_seis_ticks=6
    else:
        n_seis_ticks=6
        seis_tick_fmt='%H:%M:%S'

    for i,tr in enumerate(seis):
        ax=plt.subplot(len(seis)+3,1,i+1+3)
        tr.spectrogram(title='',log=False,samp_rate=25,dbscale=True,per_lap=0.5,mult=25.0,wlen=6,cmap=color_map,axes=ax)
        ax.set_yticks([3,6,9,12])
        ax.set_ylabel(tr.stats.station+'\n'+tr.stats.channel,fontsize=5,
                                                             rotation='horizontal',
                                                             multialignment='center',
                                                             horizontalalignment='right',
                                                             verticalalignment='center')
        ax.yaxis.set_ticks_position('right')
        ax.tick_params('y',labelsize=4)

        if i!=len(seis)-1:
            ax.set_xticks([])
        else:
            d_sec=np.linspace(0,seismic_plot_duration,n_seis_ticks)
            ax.set_xticks(d_sec)
            T=[tr.stats.starttime+dt for dt in d_sec]
            ax.set_xticklabels([t.strftime(seis_tick_fmt) for t in T])
            ax.tick_params('x',labelsize=5)
            ax.set_xlabel('{:.0f} Minute Local Seismic Data'.format(round(tr.stats.endtime-tr.stats.starttime)/60))

    ###################################################
    ###################################################


    plt.subplots_adjust(left=0.08,right=.94,top=0.92,bottom=0.1,hspace=0.1)
    
    jpg_file=utils.save_file(plt,config,dpi=250)

    return jpg_file

def xcorr_align_stream(st,config):

    shift_len = config.cc_shift_length
    shifts = []
    for i, tr in enumerate(st):
        c = correlate(st[0].data, tr.data, shift_len)
        a, b = xcorr_max(c)
        if b < 0:
            a = c.argmax() - shift_len
        shifts.append(a / tr.stats.sampling_rate)

    group_streams = Stream()
    T1 = st[0].copy().stats.starttime
    T2 = st[0].copy().stats.endtime
    for i, tr in enumerate(st):
        tr = tr.copy().trim(
            tr.stats.starttime - shifts[i],
            tr.stats.endtime - shifts[i],
            pad=True,
            fill_value=0,
        )
        tr.trim(tr.stats.starttime + 1, tr.stats.endtime - 1, pad=True, fill_value=0)
        tr.stats.starttime = T1
        group_streams += tr

    ST = st[0].copy()
    for tr in st[1:]:
        ST.data = ST.data + tr.data
    ST.data = (ST.data / len(st)) * config.digouti
    ST.trim(T1, T2)
    return ST


def create_message(t1,t2,config,volcano,azimuth,d_Azimuth,velocity,mx_pressure):
    # create the subject line
    subject='{} Airwave Detection'.format(volcano['volcano'])

    # create the test for the message you want to send
    message='{} alarm:\n'.format(config.alarm_name)
    message='{}{} detection!\n\n'.format(message,volcano['volcano'])
    message='{}Start: {} (UTC)\nEnd: {} (UTC)\n\n'.format(message,t1.strftime('%Y-%m-%d %H:%M'),t2.strftime('%Y-%m-%d %H:%M'))
    t1_local=Timestamp(t1.datetime,tz='UTC')
    t2_local=Timestamp(t2.datetime,tz='UTC')
    t1_local=t1_local.tz_convert(os.environ['TIMEZONE'])
    t2_local=t2_local.tz_convert(os.environ['TIMEZONE'])
    message='{}Start: {} ({})'.format(message,t1_local.strftime('%Y-%m-%d %H:%M'),t1_local.tzname())
    message='{}\nEnd: {} ({})\n\n'.format(message,t2_local.strftime('%Y-%m-%d %H:%M'),t2_local.tzname())

    message='{}Azimuth: {:+.1f} degrees\n'.format(message,azimuth)
    message='{}d_Azimuth: {:+.1f} degrees\n'.format(message,d_Azimuth)
    message='{}Velocity: {:.0f} m/s\n'.format(message,velocity*1000)
    message='{}Max Pressure: {:.1f} Pa'.format(message,mx_pressure)

    return subject, message