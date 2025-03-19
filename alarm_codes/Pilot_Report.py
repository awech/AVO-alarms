import os, sys
import pandas as pd
from obspy import UTCDateTime
import requests
from zipfile import ZipFile
import numpy as np
import socket
import shapefile
from shutil import rmtree
from obspy.geodetics.base import gps2dist_azimuth
import re
import matplotlib as m
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from textwrap import wrap
import traceback
import urllib3
from pathlib import Path


current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
from utils import messaging, plotting, processing


urllib3.disable_warnings()
socket.setdefaulttimeout(15)

def run_alarm(config, T0, test_flag=False, mm_flag=True, icinga_flag=True):

    state_message = '{} (UTC) No new pilot reports'.format(T0.strftime('%Y-%m-%d %H:%M'))
    state = 'OK'

    # volcs=pd.read_csv('alarm_aux_files/volcanoes_kml.txt',delimiter='\t',names=['Volcano','kml','Lon','Lat'])
    VOLCS = pd.read_excel(config.volc_file)
    volcs = VOLCS[VOLCS['PIREP'] == 'Y']

    T2 = T0
    T1 = T2 - config.duration
    filetype = 'shp'
    t1 = '&year1={}&month1={}&day1={}&hour1={}&minute1={}'.format(T1.strftime('%Y'),
                                                                  T1.strftime('%m'),
                                                                  T1.strftime('%d'),
                                                                  T1.strftime('%H'),
                                                                  T1.strftime('%M'))
    t2 = '&year2={}&month2={}&day2={}&hour2={}&minute2={}'.format(T2.strftime('%Y'),
                                                                  T2.strftime('%m'),
                                                                  T2.strftime('%d'),
                                                                  T2.strftime('%H'),
                                                                  T2.strftime('%M'))
    new_url = '{}?fmt={}{}{}'.format(os.environ['PIREP_URL'], filetype, t1, t2)

    try:
        with open(config.zipfilename, 'wb') as f:
            resp = requests.get(new_url, verify=False, timeout=10)
            f.write(resp.content)
    except:
        print('Request error')
        state = 'WARNING'
        state_message = '{} (UTC) PIREP webpage error. Cannot retrieve shape file'.format(T0.strftime('%Y-%m-%d %H:%M'))
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return
    try:
        archive = ZipFile(config.zipfilename, 'r')
    except:
        print('No new pilot reports')
        os.remove(config.zipfilename)
        messaging.icinga(config, state, state_message, send=icinga_flag)
        return


    archive.extractall(path=config.tmp_zipped_dir)
    #shp_path=config.tmp_zipped_dir+'/stormattr_{}_{}'.format(T1.strftime('%Y%m%d%H%M'),T2.strftime('%Y%m%d%H%M'))
    shp_path = config.tmp_zipped_dir+'/pireps_{}_{}'.format(T1.strftime('%Y%m%d%H%M'), T2.strftime('%Y%m%d%H%M'))


    #read file, parse out the records and shapes
    sf = shapefile.Reader(shp_path)
    fields = [x[0] for x in sf.fields][1:]
    records = sf.records()
    shps = [s.points for s in sf.shapes()]


    #write into a dataframe
    df = pd.DataFrame(columns=fields, data=records)
    df['VALID'] = pd.to_datetime(df['VALID'])
    df = df[df.LAT>49]


    #### delete duplicate events with different text versions in the 'REPORT' field'
    A = df.copy()
    del A['REPORT']
    A.drop_duplicates(inplace=True)
    df = df.loc[A.index]
    df.reset_index(drop=True, inplace=True)

    OLD = get_old_pireps(config, T0)

    for i, report in enumerate(df.REPORT.values):

        tmp_t = df.loc[i].VALID
        latstr = str(df.loc[i].LAT-np.floor(df.loc[i].LAT)).split('.')[1][:3]
        lonstr = str(-df.loc[i].LON-np.floor(-df.loc[i].LON)).split('.')[1][:3]
        latlon = int('{}{}'.format(latstr,lonstr))
        tmp_t = tmp_t + pd.to_timedelta(latlon, 'us')
        tmp = pd.DataFrame(data={'lats':df.loc[i].LAT.astype('float'),
                                  'lons':df.loc[i].LON.astype('float'),
                                  'time':tmp_t}, index=[0])
        tmp.set_index('time', inplace=True)

        tmp = tmp[~tmp.isin(OLD).all(1)]

        if tmp.empty:
            continue

        trigger = check_volcano_mention(report)
        
        if trigger:

            state_message = '{} (UTC) {}'.format(T0.strftime('%Y-%m-%d %H:%M'), report)

            # DIST = np.array([])
            # for lat, lon in zip(volcs.Lat.values, volcs.Lon.values):
            # 	dist, azimuth, az2=gps2dist_azimuth(lat, lon, df.loc[i].LAT, df.loc[i].LON)
            # 	DIST = np.append(DIST, dist/1000.)

            # if DIST.min() < config.max_distance:

            volcs = processing.volcano_distance(df.loc[i].LON, df.loc[i].LAT, volcs)
            volcs = volcs.sort_values('distance')

            if volcs.distance.min() < config.max_distance:
                if df.loc[i].URGENT == 'F':
                    state = 'WARNING'
                    config.send_email = config.non_urgent
                elif df.loc[i].URGENT == 'T':
                    state = 'CRITICAL'
                    config.send_email = True

                A = volcs.copy()

                UTC_time_text = '{} UTC'.format(UTCDateTime(df.loc[i].VALID).strftime('%Y-%m-%d %H:%M'))
                height_text   = get_height_text(report)
                pilot_remark  = get_pilot_remark(report)

                #### Generate Figure ####
                try:
                    filename = plot_fig(config, df, i, A, UTC_time_text, height_text, pilot_remark)
                except:
                    print('Error generating figure...')
                    b = traceback.format_exc()
                    err_message = ''.join('{}\n'.format(a) for a in b.splitlines())
                    print(err_message)
                    filename = []

                ### Craft message text ####
                subject, message = create_message(df, i, A, UTC_time_text, height_text, pilot_remark)

                ### Post to Mattermost ###
                messaging.post_mattermost(config, subject, message, attachment=filename, send=mm_flag, test=test_flag)

                ### Send message to duty person ###
                if config.send_email:
                    messaging.send_alert(config.alarm_name, subject, message, attachment=filename, test=test_flag)

                # delete the file you just sent
                if filename:
                    os.remove(filename)

                # OLD = OLD.append(tmp)
                OLD = pd.concat([OLD, tmp])


    OLD.to_csv(config.outfile, float_format='%.6f', index_label='time', sep='\t', date_format='%Y%m%dT%H%M%S.%f')
    os.remove(config.zipfilename)
    rmtree(config.tmp_zipped_dir)

    messaging.icinga(config, state, state_message, send=icinga_flag)


def check_volcano_mention(report):
    trigger = False
    report = report.upper()
    tmp_report = report.replace('VAR', '')
    tmp_report = tmp_report.replace('VAL', '')
    tmp_report = tmp_report.replace('VAT', '')
    tmp_report = tmp_report.replace('NEVA', '')
    tmp_report = tmp_report.replace('AVAIL', '')
    tmp_report = tmp_report.replace('SVA', '')
    tmp_report = tmp_report.replace('PREVAIL', '')
    tmp_report = tmp_report.replace('VASI', '')
    tmp_report = tmp_report.replace('TOLOVANA', '')
    tmp_report = tmp_report.replace('GAVANSKI', '')
    tmp_report = tmp_report.replace('CORDOVA', '')
    tmp_report = tmp_report.replace('ADVANC', '')
    tmp_report = tmp_report.replace('INVAD', '')
    tmp_report = tmp_report.replace('VACINITY', '')
    tmp_report = tmp_report.replace('SULLIVAN', '')
    tmp_report = tmp_report.replace('BELIEVABLE', '')
    tmp_report = tmp_report.replace('DURD VA RWY', '')
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
    elif 'SULPHUR' in report:
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


def get_old_pireps(config, T0):

    OLD = pd.read_csv(config.outfile, delimiter='\t', parse_dates=['time'])
    OLD = OLD.drop_duplicates(keep=False)
    OLD = OLD[OLD['time']>(T0-config.duration-10).strftime('%Y%m%d %H%M%S.%f')]

    OLD['lats'] = OLD.lats.values.astype('float')
    OLD['lons'] = OLD.lons.values.astype('float')

    OLD.set_index('time', inplace=True)

    return OLD


def get_height_text(report):
    height = report.split('/FL')[-1].split('/')[0]
    try:		
        height_text = 'Flight level: {:.0f},000 feet asl'.format(int(height)/10.)
    except:
        height_text = 'Flight level: UNKNOWN'

    return height_text


def get_pilot_remark(report):
    
    FL = re.compile('(.*)fl(\d+)(.*)', re.MULTILINE)
    RM = re.compile('(RM)*(.*)')

    fields = report.split('/')
    pilot_remark = 'Pilot Remark: {}'.format(RM.sub(r'\2', fields[-1]).lower().lstrip())
    t1 = FL.sub(r'\1', pilot_remark)
    t2 = FL.sub(r'\2', pilot_remark)
    t3 = FL.sub(r'\3', pilot_remark)
    try:
        pilot_remark = '{}{:.0f},000 feet asl{}'.format(t1, int(t2)/10., t3)
    except:
        pass

    return pilot_remark


def create_message(df, i, A, UTC_time_text, height_text, pilot_remark):

    t = pd.Timestamp(df.loc[i].VALID, tz='UTC')
    t_local = t.tz_convert(os.environ['TIMEZONE'])
    Local_time_text = '{} {}'.format(t_local.strftime('%Y-%m-%d %H:%M'), t_local.tzname())


    message = '{}\n{}\n{}\n{}'.format(UTC_time_text,
                                      Local_time_text,
                                      height_text,
                                      pilot_remark)
    message = '{}\nLatitude: {:.3f}\nLongitude: {:.3f}\n'.format(message, df.loc[i].LAT, df.loc[i].LON)

    v_text = ''
    A = A.sort_values('distance')
    for j, row in A[:3].iterrows():
        v_text = '{}{} ({:.0f} km), '.format(v_text, row.Volcano, row.distance)
    v_text = v_text.replace('_', ' ')
    message = '{}Nearest volcanoes: {}\n'.format(message, v_text[:-2])
    message = '{}\n--Original Report--\n{}'.format(message, df.loc[i].REPORT)
    print(message)

    if df.loc[i].URGENT == 'T':
        subject = 'URGENT! Activity possible at: {}'.format(v_text[:-2])
    else:
        subject = 'Activity possible at: {}'.format(v_text[:-2])

    return subject, message


def plot_fig(config, df, i, A, UTC_time_text, height_text, pilot_remark):
    m.use('Agg')

    # Create figure & axis
    fig, ax = plt.subplots(figsize=(4,4))	

    # Make the map
    lat0 = df.loc[i].LAT
    lon0 = df.loc[i].LON
    m_map,inmap=plotting.make_map(ax, lat0, lon0, main_dist=150, inset_dist=400, scale=50)

    # Add plane location and nearby volcanoes
    m_map.plot(A.sort_values('distance').Longitude.values[:10], A.sort_values('distance').Latitude.values[:10], '^',
               latlon=True,
               markerfacecolor='forestgreen',
               markeredgecolor='black',
               markersize=4,
               markeredgewidth=0.5)
    m_map.plot(lon0, lat0, 'o',
               latlon=True,
               markeredgecolor='k',
               markersize=6,
               markerfacecolor='gold',
               markeredgewidth=0.5)
    
    # Write title & caption
    m_map.ax.set_title(UTC_time_text+'\n'+height_text)
    m_map.ax.set_xlabel('\n'.join(wrap(pilot_remark,60)), labelpad=10, fontsize=8)

    # draw rectangle on inset map
    bx, by = inmap(m_map.boundarylons, m_map.boundarylats)
    xy = list(zip(bx, by))
    mapboundary = Polygon(xy, edgecolor='firebrick', linewidth=0.5, fill=False)
    inmap.ax.add_patch(mapboundary)

    # save file
    jpg_file = plotting.save_file(plt, config, dpi=250)

    return jpg_file
