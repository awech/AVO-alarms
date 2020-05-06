# AVO-alarms
python codes used for geophysical alarms at AVO

### Python Dependencies
- pandas<br>
- numpy<br>
- obspy<br>
- matplotlib<br>
- Basemap<br>
- PIL (pillow)<br>
- xlrd<br>
- dotenv<br>
- beautifulsoup4<br>
- tomputils (optional for Mattermost)<br>

### Running it...
You'll need to edit .env_example with the relevant system parameters and rename the file .env<br>
These variables get committed to environment variables when importing anything from /alarm_codes<br><br>
Run the code:
main.py <alarm_config> <datetime> <br>
For example: ./main.py Pavlof_RSAM_config 201701020205<br><br>
It can also be run without a datestamp, in which case it will use the most recent minute as its time.<br><br>
An example of how we run a cron minutely on the Cleveland infrasound array, CLCO:<br>
\* \* \* \* \* cd /alarms; python main.py CLCO_Infrasound_config > /dev/null 2>&1


### Notifications:
Edit the .distribution_example.xlsx to include the relevant recipient addresses and rename to distribution.xlsx<br>
It is important that column headers match the name of the alarm config file names (but replacing _ with a space)

