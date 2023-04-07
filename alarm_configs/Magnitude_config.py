alarm_type = 'Magnitude'
alarm_name = 'Magnitude' 

outfile = 'alarm_aux_files/Recent_earthquakes.txt'
volc_file = 'alarm_aux_files/volcano_list.xlsx'

MAGMIN = 2.5
MAXDEP = 35
DISTANCE = 10
DURATION = 2*3600

mattermost_channel_id = '1yxp3dhsjtd55jbbrawddzkk6h'

mm_response_channels = {
	'Tanaga': 'dcimdcioh7g8tpywkaccf1uruc',
	'Takawangha': 'dcimdcioh7g8tpywkaccf1uruc',
	'Aniakchak': 'eoeizwgp8bdnpmqpcicb7tjqbw',
	'Trident': 'd4e8jhmay7rbfe19za1zywwhpe',
	'Katmai': 'd4e8jhmay7rbfe19za1zywwhpe',
}