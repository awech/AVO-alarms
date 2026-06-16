import os

import numpy as np
import pandas as pd

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def create_message(swarm):

    tmin = pd.Timestamp(swarm.time.min(), tz="UTC")
    tmax = pd.Timestamp(swarm.time.max(), tz="UTC")
    dt = tmax - tmin
    hours = np.floor(dt.total_seconds() / 3600)
    minutes = np.round((dt.total_seconds() - hours * 3600) / 60)

    message = f"{len(swarm)} events in {hours:.0f}h {minutes:.0f}m"
    message += "\n\n***--- UTC ---***"
    message += f"\n**First:** {tmin.strftime('%Y-%m-%d %H:%M')}"
    message += f"\n**Last:** {tmax.strftime('%Y-%m-%d %H:%M')}"

    tmin_local = tmin.tz_convert(os.environ["TIMEZONE"])
    tmax_local = tmax.tz_convert(os.environ["TIMEZONE"])

    message += f"\n\n***--- {tmax_local.tzname()} ---***"
    message += f"\n**First:** {tmin_local.strftime('%Y-%m-%d %H:%M')}"
    message += f"\n**Last:** {tmax_local.strftime('%Y-%m-%d %H:%M')}"

    message += f"\n\n**Magnitude range:** {swarm.mag.min():.1f} - {swarm.mag.max():.1f}"
    num_nan_mags = len(np.where(np.isnan(swarm.mag))[0])
    if num_nan_mags == 1:
        message += f" ({num_nan_mags:.0f} event with unassigned magnitude)"
    elif num_nan_mags > 1:
        message += f" ({num_nan_mags:.0f} events with unassigned magnitude)"

    message += (
        f"\n**Depth range:** {swarm.depth.min():.1f} - {swarm.depth.max():.1f} km"
    )
    num_nan_deps = len(np.where(np.isnan(swarm.depth))[0])
    if num_nan_deps == 1:
        message += f" ({num_nan_deps:.0f} event with unassigned depth)"
    elif num_nan_deps > 1:
        message += f" ({num_nan_deps:.0f} events with unassigned depth)"

    subject = f"Earthquake swarm at {swarm.iloc[0].v_name}"

    return subject, message
