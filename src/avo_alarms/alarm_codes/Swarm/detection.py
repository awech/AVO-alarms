import os
from itertools import combinations

import numpy as np
import pandas as pd
import utm
from sklearn.cluster import DBSCAN

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)


def build_download_url(T0, config):

    T2 = T0
    T1 = T2 - config.DURATION
    URL = (
        f"{os.environ['FDSN_URL']}"
        f"starttime={T1.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&endtime={T2.strftime('%Y-%m-%dT%H:%M:%S')}"
        f"&maxdepth={config.MAXDEP}"
        "&format=csv"
    )
    return URL


def check_swarm_continue(T0, config, old_eq_df, new_eq_df, col_key="event_id"):

    tmp_new_df = new_eq_df.copy()
    drop_columns = [col for col in tmp_new_df if col not in old_eq_df.columns]
    tmp_new_df = tmp_new_df.drop(columns=drop_columns)
    all_eq_df = pd.concat([old_eq_df, tmp_new_df], ignore_index=True).drop_duplicates(
        col_key
    )
    swarm_continue = get_swarms(all_eq_df.copy(), T0, config)
    swarm_continue = [swarm.loc[~swarm[col_key].isin(old_eq_df[col_key])] for swarm in swarm_continue]
    swarm_continue = [swarm for swarm in swarm_continue if len(swarm)>0]

    return swarm_continue


def compare_swarms(swarms):
    flag = True
    test_swarms = swarms.copy()
    while flag:
        SWARM_COMBOS = list(combinations(range(len(test_swarms)), 2))

        if len(SWARM_COMBOS) > 0:
            remove_swarm_ind = []
            flag_list = []
            for ind_combo in SWARM_COMBOS:
                # check for duplicate swarm detections
                if test_swarms[ind_combo[0]].equals(test_swarms[ind_combo[1]]):
                    logger.info("found equals")
                    flag_list.append(True)
                    remove_swarm_ind.append(ind_combo[0])
                    continue

                # check for overlap, and keep the shortest duration event
                int_df = pd.merge(
                    test_swarms[ind_combo[0]],
                    test_swarms[ind_combo[1]],
                    how="inner",
                    on=["id", "id"],
                )
                if len(int_df) > 0:
                    logger.info("overlap")
                    dt0 = (
                        test_swarms[ind_combo[0]].Time.max()
                        - test_swarms[ind_combo[0]].Time.min()
                    )
                    dt1 = (
                        test_swarms[ind_combo[1]].Time.max()
                        - test_swarms[ind_combo[1]].Time.min()
                    )
                    remove_swarm_ind.append(ind_combo[np.argmax([dt0, dt1])])
                    flag_list.append(True)
                else:
                    logger.info("no overlap")
                    flag_list.append(False)

            # update swarms list with duplicate/overlapping swarms removed
            test_swarms = [
                test_swarms[x]
                for x in range(len(test_swarms))
                if x not in remove_swarm_ind
            ]
            flag = any(flag_list)
        else:
            flag = False

    return test_swarms


def get_swarms(DF, T0, config):

    df = DF.copy()

    t_str_fmt = "%Y-%m-%d %H:%M:%S"
    lat0 = df.latitude.mean()
    lon0 = df.longitude.mean()
    ZN_LET = utm.latitude_to_zone_letter(lat0)
    ZN_NUM = utm.latlon_to_zone_number(lat0, lon0)

    east, north, *_ = utm.from_latlon(
        df.latitude, df.longitude, force_zone_number=ZN_NUM, force_zone_letter=ZN_LET
    )
    df["x"] = east / 1000
    df["y"] = north / 1000

    SWARMS = []
    for params in config.swarm_parameters:
        # scale time to match distance
        cat_df = df.copy()[df["time"] > (T0 - params["MAX_EVT_TIME"]).strftime(t_str_fmt)]
        if len(cat_df) == 0:
            continue
        t = cat_df.time
        dtime = np.array([(t0 - t.min()).total_seconds() for t0 in t])
        dtime = dtime * (params["MAX_EVT_DISTANCE"] / float(params["MAX_EVT_TIME"]))
        # put distance and time together
        X = np.array([cat_df["x"], cat_df["y"], dtime]).T
        db = DBSCAN(
            eps=params["MAX_EVT_DISTANCE"], min_samples=params["MIN_NUM_EVT"]
        ).fit(X)

        cat_df.loc[:, "label"] = db.labels_
        cat_df.loc[:, "param_duration"] = float(params["MAX_EVT_TIME"])
        all_detects = cat_df[cat_df["label"] > -1]
        # NOISE = cat_df[cat_df['label']==-1]

        for i in all_detects.label.unique():
            df = cat_df[cat_df["label"] == i]
            SWARMS.append(df.copy())

    return SWARMS
