alarm_type = 'Pilot_Report'
alarm_name = 'PIREP' 

zipfilename    = 'alarm_aux_files/tmp.zip'
tmp_zipped_dir = 'alarm_aux_files/tmp_zipped_dir'
outfile        = 'alarm_aux_files/PIREPs.txt'

max_distance  = 200		# maximum distance for sending an alert
duration 	  = 60*60	# time limit in seconds for remembering strokes
non_urgent    = False	# send notification if classified as non-urgent or not

mattermost_channel_id = 'fdde17wkrfdqze785wt69mrqeo'