alarm_type = "Tremor"				# this designates which alarm module will be imported and executed
alarm_name = "Pavlof Tremor"		# this is the alarm name sent to icinga and in message alerts
volcano = "Pavlof"

##############################################
######### alarm threshold parameters #########
NSLC = [
    {"nslc":  "AV.HAG..BHZ", "lat":	55.317, "lon":	-161.905 },
    {"nslc": "AV.PS4A..BHZ", "lat":	55.346, "lon":	-161.857 },
    {"nslc":  "AV.PVV..BHZ", "lat":	55.373, "lon":	-161.792 },
    {"nslc": "AV.PS1A..BHZ", "lat":	55.420, "lon":	-161.744 },
    {"nslc": "AV.PN7A..BHZ", "lat":	55.433, "lon":	-161.997 },
    {"nslc": "AV.PV6A..BHZ", "lat":	55.507, "lon":	-161.9714},
]
##############################################
##############################################


##############################################
######### alarm threshold parameters #########
duration	   = 3600 			  # [seconds] how far into past to look for detections
threshold      = 25   			  # [minutes] required in past hour for notification
rsam_station   = "AV.PS1A..BHZ"   # N.S.L.C - channel to be used for RSAM threshold test
rsam_threshold = 180  			  # RSAM threshold for above nslc. Alarm won"t send if below this level
##############################################
##############################################


##############################################
####### waveform processing parameters #######
window_length = 5 * 60 # duration value in seconds
latency       = 10     # seconds between timestamps and end of data window
taper	      = 5 	   # seconds to taper beginning and end of trace before filtering
f1		      = 1.0    # minimum frequency for bandpass filter
f2		      = 6.0    # maximum frequency for bandpass filter
highpass      = 8.0
lowpass       = 0.1
##############################################
##############################################


##############################################
######## envelope location parameters ########
min_sta       = 4     # minimum number of stations for detection
Cmin          = 0.5   # minimum cross-correlation coefficient
Cmax          = 0.95  # minimum cross-correlation coefficient
bstrap        = 10    # number of bootstrap iterations
bstrap_prct   = 0.04  # percentage of data to throw away in each iteration
max_scatter   = 8.0   # maximum horizontal scatter in km

from numpy import arange
grid = {
    "lons": arange(-162.22, -161.64 + 0.001, 0.02),
	"lats": arange(  55.18,   55.56 + 0.001, 0.02),
	"deps": arange(    1.0,    12.0 + 0.001, 0.2 )
   }
phase_list = ["3kmps"]
##############################################
##############################################


##############################################
########## supporting file locations #########
grid_file    = "Pavlof_tremor_grid.npz"  # location of grid/model file
##############################################
##############################################