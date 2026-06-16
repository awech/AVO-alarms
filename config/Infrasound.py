alarm_type = 'Infrasound'			# this designates which alarm module will be imported and executed
alarm_name = 'SDPI Infrasound'	# this is the alarm name sent to icinga and in message alerts

# Infrasound channels list
NSLC = [
    {"nslc": "AV.SDPI.01.HDF"},
    {"nslc": "AV.SDPI.02.HDF"},
    # {"nslc": "AV.SDPI.03.HDF"},
    {"nslc": "AV.SDPI.04.HDF"},
    {"nslc": "AV.SDPI.05.HDF"},
    {"nslc": "AV.SDPI.06.HDF"},
]

# Target list to be monitored
# Need target name and location for each target
# Azimuthal tolerance is in degrees
# seismic_nslc is a list of seismic channels to be plotted with infrasound on detect
TARGETS = [
    {
        "name": "Pavlof",
        "az_tolerance": 8,
        "min_pa": 2.0,
        "seismic_nslc": ["AV.PV6A..BDF", "AV.PV6A..SHZ", "AV.PN7A..BHZ", "AV.PS4A..BHZ"]
    },
    {
        "name": "Veniaminof",
        "az_tolerance": 6,
        "min_pa": 0.5,
        "seismic_nslc": ["AV.VNSG..BHZ", "AV.VNWF..BHZ", "AV.VNCG..BHZ"]
    },
    {
        "name": "Aniakchak",
        "az_tolerance": 3,
        "min_pa": 0.3,
        "seismic_nslc": ["AV.ANPK..BHZ", "AV.ANNW..BHZ", "AV.BPPC..BHZ"]
    },
    {
        "name": "Shishaldin",
        "az_tolerance": 5,
        "min_pa": 0.5,
        "seismic_nslc": ["AV.SSBA..BHZ", "AV.ISNN..BHZ", "AV.WTUG..BHZ"]
    },
]

duration  = 3*60 # duration value in seconds
latency   = 10.0 # seconds between timestamps and end of data window
taper_val = 5.0  # seconds to taper beginning and end of trace before filtering
f1        = 1.0  # minimum frequency for bandpass filter
f2        = 10.0 # maximum frequency for bandpass filter

min_cc    = 0.6     # min normalized correlation coefficient to accept
min_chan  = 3       # minimum # of channels for code to run
cc_shift_length = 6 # maximum seconds to shift in cross-correlation