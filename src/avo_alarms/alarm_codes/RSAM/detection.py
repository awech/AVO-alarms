import os
from pathlib import Path

import numpy as np
from obspy import read_inventory

from avo_alarms.utils.processing import volcano_distance
from avo_alarms.utils.setup_utils import get_logger, load_volcano_list

logger = get_logger(__name__)


def RSAM_to_DR(tr, volcano_name, VELOCITY=1.5, FREQ=2, Q=200):
    """Convert RSAM (counts) to Reduced Displacement (cm^2).

    VELOCITY = 1.5   # km/s
    FREQ = 2         # dominant frequency (Hz)
    Q = 200          # quality factor

    Parameters
    ----------
    tr : obspy.Trace
        Trace object with seismic data.
    volcano_name : str
        Name of the target volcano for distance calculation.
    VELOCITY : float, optional
        Surface wave velocity in km/s, by default 1.5
    FREQ : int, optional
        Dominant frequency in Hz, by default 2
    Q : int, optional
        Quality factor, by default 200

    Returns
    -------
    float
        Reduced displacement value in cm^2.
    """

    VOLCS = load_volcano_list()
    volcs = VOLCS[VOLCS["Name"] == volcano_name].copy()

    xml_file = Path(os.getenv("STATION_XML", "blank"))
    if not xml_file.exists():
        logger.error("Station XML file missing")
        return

    inventory = read_inventory(xml_file)

    coords = inventory.get_coordinates(tr.id)
    gain = inventory.get_response(
        tr.id, tr.stats.starttime
    ).instrument_sensitivity.value  # counts/m/s

    volcs = volcano_distance(coords["longitude"], coords["latitude"], volcs)
    R = volcs.iloc[0].distance

    r = R * 1000 * 100
    velocity = VELOCITY * 1000 * 100
    wavelength = velocity / FREQ

    #### account for attenuation ####
    numerator = -np.pi * FREQ * r
    denominator = Q * velocity
    atten_factor = np.exp(numerator / denominator)

    lvl = np.sqrt(np.mean(np.square(tr.data)))  # rms level in counts
    rms_v = lvl / (gain * atten_factor)         # rms in m/s corrected for gain & attenuation
    rmssta = rms_v * 100 / (2 * np.pi * FREQ)   # converted to cm
    DR = rmssta * np.sqrt(r * wavelength)       # converted to reduced displacement

    return DR
