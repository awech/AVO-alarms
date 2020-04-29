#!/home/rtem/miniconda/envs/py_alarms/bin/python
# -*- coding: utf-8 -*-

import os
import pandas as pd
from glob import glob
import numpy as np

import sys
sys.path.append('/alarms3')
from alarm_codes import utils

A=pd.read_excel(os.environ['HOME_DIR']+'/distribution.xlsx')
del A['Error']
A.rename(columns={'Name':'who','Email':'address'},inplace=True)

who=A['who']
add=A['address']
A=A.replace(0.0,np.nan,regex=True)
A=A.replace('x',1.0,regex=True)
A=A.replace('o',0.0,regex=True)
af=A.copy()
del af['who']
del af['address']


sums=af.sum(axis='columns',numeric_only=True)
sums=sums[np.invert(sums>=0)]
A=A.drop(sums.index)
who=who.drop(sums.index)
add=add.drop(sums.index)
A['who']=who
A['address']=add
del A['address']

A['who']=A.who.str.capitalize()
A=A.sort_values(by='who')
A=A.reset_index(drop=True)

def highlight_vals(val):
	string='font-family: Helvetica; '
	if val=='x':
		string+='background-color: #8CDD81; text-align: center; color: #3B5323; font-weight: bold;'
	elif val=='o':
		string+='background-color: #FBEC5D; text-align: center; color: #8B7500; font-weight: bold;'
	elif 'cell' in val:
		string+='text-align: left; font-weight: bold; color: red;'
	elif 'email' in val:
		string+='text-align: left;'
	return string

A=A.replace(np.nan,' ',regex=True)
A=A.replace(0.0,'o',regex=True)
A=A.replace(1.0,'x',regex=True)
A=A.replace('_',' ',regex=True)
A=A.replace('phone','cell',regex=True)

B=A.style.set_properties(**{'font-family':'Hevletica'})
B=B.applymap(highlight_vals)
a=B.render()
g=open(os.environ['HOME_DIR']+'/www/index.html','w')
g.write(a)
g.close()