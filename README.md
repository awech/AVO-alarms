# AVO-alarms
Python codes used for geophysical alarms at AVO. Currently (2023-Sep-06) running on Python 3.8.17

## Python Dependencies
- pandas<br>
- obspy<br>
- Basemap<br>
- cartopy<br>
- PIL (pillow)<br>
- xlrd<br>
- dotenv<br>
- shapely<br>
- utm<br>
- scikit-learn<br>
- enveloc (only for Tremor module)<br>
- shapefile (for Pilot_Report module)<br>
- beautifulsoup4 (for SO2, NOAA_CIMSS, & SIGMET modules)<br>
- tomputils (optional for Mattermost)<br>

## Running it...
You'll need to edit .env_example with the relevant system parameters and rename the file .env<br>
These variables get committed to environment variables when importing anything from /alarm_codes<br><br>
Run the code:<br>
`main.py <alarm_config> <datetime>` <br>
For example:<br>
`./main.py Pavlof_RSAM_config 201701020205`<br><br>
It can also be run without a datestamp, in which case it will use the most recent minute as its time.<br><br>
An example of how we run a cron minutely on the Cleveland infrasound array, CLCO:<br>
`* * * * * cd /alarms; python main.py CLCO_Infrasound_config > /dev/null 2>&1`<br><br>

## Notifications:
Edit the .distribution_example.xlsx to include the relevant recipient addresses and rename to distribution.xlsx<br>
It is important that column headers match the name of the alarm config file names (but replacing _ with a space)

