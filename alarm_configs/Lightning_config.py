alarm_type = 'Lightning'
alarm_name = 'Lightning' 

volc_file = 'alarm_aux_files/volcano_list.xlsx'
outfile    = 'alarm_aux_files/Lightning_last.txt'

dist1 = 20			# distance for inner ring (in km)
dist2 = 100			# distance for outer ring (in km)

duration = 60*60	# time limit in seconds for remembering strokes

ignore_volcanoes = ['Buzzard Creek', 'St. Michael', 'Ingakslugwat Hills', 'Behm Canal-Rudyerd Bay']

mattermost_channel_id = 'bbee81rp13n68mstu33xf3b88a'