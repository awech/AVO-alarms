#!/home/rtem/.conda/envs/alarms/bin/python
# -*- coding: utf-8 -*-

import os
import sys
sys.path.append('/alarms')
from obspy import UTCDateTime
from alarm_codes import utils

if os.getenv('FROMCRON') == 'yep':
    file=os.environ['LOGS_DIR']+'/Metadata-'+UTCDateTime.now().strftime('%Y%m%d-%H')+'.out'
    os.system('touch {}'.format(file))
    f=open(file,'a')
    sys.stdout=sys.stderr=f

utils.update_stationXML()