# AVO-alarms
python codes used for geophysical alarms at AVO

## Python Dependencies
- pandas<br>
- numpy<br>
- obspy<br>
- scipy<br>
- matplotlib<br>
- Basemap<br>
- PIL (pillow)<br>
- xlrd<br>
- dotenv<br>
- enveloc (only for Tremor module)<br>
- shapefile (for Pilot_Report module)<br>
- beautifulsoup4 (for SO2 & NOAA_CIMSS modules)<br>
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
Note: if using the Tremor.py module, you'll need to add /bin/XC_loc/ to your python path

## Notifications:
Edit the .distribution_example.xlsx to include the relevant recipient addresses and rename to distribution.xlsx<br>
It is important that column headers match the name of the alarm config file names (but replacing _ with a space)

