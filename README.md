# AVO-alarms
python codes used for geophysical alarms at AVO

### Python Dependencies
pandas<br>
numpy<br>
obspy>=1.1<br>
matplotlib<br>
PIL<br>

### Running it...
You'll need to edit .sys_config_example.py with the relevant system parameters and rename the file sys_config.py<br>
Run the code:
main.py <alarm_config> <datetime str> <br>
eg. main.py Pavlof_RSAM 201701020205<br>
It can also be run without a datestamp, in which case it will use the most recent minute as its time<br><br>
An example of how we run a cron minutely on the Cleveland infrasound array, CLCO:<br>
* * * * * cd /alarms; main.py CLCO_Infrasound > /dev/null 2>&1


### Notifications:
Edit the .distribution_example.xlsx to include the relevant recipient addresses and rename to distribution.xlsx<br>
It is important that column headers match the name of the alarm config file names (but replacing _ with a space)

