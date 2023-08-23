alarm_type = 'Swarm'
alarm_name = 'Earthquake Swarm' 

outfile = 'alarm_aux_files/Recent_swarms.txt'
volc_file = 'alarm_aux_files/volcano_list.xlsx'

# FDSN Catalog request parameters
MAGMIN = -3
MAXDEP = 40
VOLCANO_DISTANCE = 10

# Clustering parameters:
swarm_parameters = [
	{
		'Name': 'short',
		'MAX_EVT_DISTANCE': 4,		# inter-event distance in km
		'MAX_EVT_TIME': 3600,		# inter-event time in s
		'MIN_NUM_EVT': 6			# total number of events satisfying above
	},
	{
		'Number': 'long',
		'MAX_EVT_DISTANCE': 4,		# inter-event distance in km
		'MAX_EVT_TIME': 24*3600,	# inter-event time in s
		'MIN_NUM_EVT': 12			# total number of events satisfying above
	},
]

mattermost_channel_id = 'p9q5xkzc1ig9fqeef7zia7pa6y'
# icinga_service_name = 'generic alarm 1'

# mm_response_channels = {
# 	'Aniakchak': 'eoeizwgp8bdnpmqpcicb7tjqbw',
# 	'Trident': 'd4e8jhmay7rbfe19za1zywwhpe',
# 	'Katmai': 'd4e8jhmay7rbfe19za1zywwhpe',
# 	'Martin': 'd4e8jhmay7rbfe19za1zywwhpe',
# 	'Mageik': 'd4e8jhmay7rbfe19za1zywwhpe',
# 	'Novarupta': 'd4e8jhmay7rbfe19za1zywwhpe',
# }