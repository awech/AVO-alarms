"""
Detection helpers for the Lightning alarm.

Provides routines to download recent lightning strokes from the Volcview API,
partition strokes into inner/outer distance rings, compose the Icinga state
message, and convert an azimuth to a compass direction.
"""

import json
import os
import time

import numpy as np
import pandas as pd

from volc_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def download_lightning(force=False):
    """Download recent lightning strokes from the Volcview API.

    Retries up to three times. On success, renames the API columns to the
    canonical schema and parses the stroke times.

    Parameters
    ----------
    force : bool, optional
        If True, point at the global (non-AVO) data source to force data for
        testing, by default False.

    Returns
    -------
    pandas.DataFrame or None
        Strokes with columns such as ``latitude``, ``longitude``, ``time``,
        ``id``, ``dataSource``, and the API's volcano association fields.
        Returns ``None`` if all download attempts fail.
    """

    logger.info("Reading in alerts from volcview api .json file")
    attempt = 1
    max_tries = 3
    lightning_url = os.getenv("LIGHTNING_URL")
    if force:
        logger.warning("Forcing trigger by pointing to global data source")
        lightning_url = lightning_url.replace("avorecent", "recent")
        lightning_url = lightning_url.replace("avo-volcview", "volcview")
    while attempt <= max_tries:
        try:
            data = json.load(
                os.popen(
                    'curl --connect-timeout 5 -H "username:{}" -H "password:{}" -X GET {}'.format(
                        os.getenv("API_USERNAME"),
                        os.getenv("API_PASSWORD"),
                        lightning_url,
                    )
                )
            )
            strokes_df = pd.DataFrame(data["lightning"])
            if len(strokes_df) >= 1:
                column_rename = {
                    "lightningLatitude": "latitude",
                    "lightningLongitude": "longitude",
                    "lightningDate": "time",
                    "lightningId": "id",
                    "dataSource": "dataSource",
                    "volcanoName": "api_vname",
                    "volcanoLatitude": "api_vlat",
                    "volcanoLongitude": "api_vlon",
                    "nearestDistanceKm": "api_vdist",
                }
                strokes_df.rename(columns=column_rename, inplace=True)
                strokes_df["time"] = pd.to_datetime(strokes_df["time"])
                strokes_df = strokes_df[column_rename.values()]
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error getting data from Volcview-API on attempt {attempt:g}")
            logger.warning(e)
            time.sleep(2)
            attempt += 1
            strokes_df = None

    return strokes_df


def inner_outer(df, config):
    """Count strokes in the inner and outer distance rings.

    Parameters
    ----------
    df : pandas.DataFrame
        Strokes with a ``v_distance`` column (km to the volcano).
    config : object
        Configuration exposing ``dist1`` (inner ring radius, km).

    Returns
    -------
    n_ring1 : int
        Number of strokes within ``dist1`` of the volcano.
    n_ring2 : int
        Number of remaining strokes (beyond ``dist1``).
    """

    n_ring1 = len(df[df["v_distance"] < config.dist1])
    n_ring2 = len(df) - n_ring1

    return n_ring1, n_ring2


def get_state_message(state, T0_str, v_name, n_ring1, n_ring2, config):
    """Compose the Icinga state message for a lightning detection.

    Parameters
    ----------
    state : {'WARNING', 'CRITICAL'}
        Detection state, which selects the message wording.
    T0_str : str
        Formatted window end time (UTC).
    v_name : str
        Volcano name.
    n_ring1 : int
        Number of strokes within the inner ring.
    n_ring2 : int
        Number of strokes in the outer ring.
    config : object
        Configuration exposing ``dist1``, ``dist2``, and ``duration``.

    Returns
    -------
    str
        The formatted state message, including stroke counts per ring and the
        lookback window.
    """

    match state:
        case "WARNING":
            if n_ring1 + n_ring2 == 0:
                state_message = f"{T0_str} (UTC) {v_name} Lightning Detection!"
            else:
                state_message = f"{T0_str} (UTC) {v_name} Distal Lightning Detection!"
        case "CRITICAL":
            state_message = f"{T0_str} (UTC) {v_name} Lightning Detection!"
            state_message = f"{state_message} {n_ring1 + n_ring2} new strokes!"

    d1 = config.dist1
    d2 = config.dist2
    state_message = f"{state_message} {n_ring1} strokes < {d1:g} km ({d1:g} km < {n_ring2} < {d2:g} km)"
    state_message = f"{state_message} in past {config.duration/60:.0f} minutes."

    return state_message


def get_direction(azimuth):
    """Convert an azimuth to a 16-point compass direction.

    Parameters
    ----------
    azimuth : float
        Azimuth in degrees clockwise from north.

    Returns
    -------
    str
        The nearest 16-point compass label (e.g. ``"NNE"``, ``"SW"``).
    """

    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    ix = int(np.round(azimuth / (360 / len(dirs))))

    return dirs[ix % len(dirs)]
