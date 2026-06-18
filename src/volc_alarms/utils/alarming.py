import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from tabulate import tabulate


def now_utc():
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime):
    # ISO-8601 with 'Z' suffix; lexicographically sortable
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def resolve_table_name(test, table=None):
    """Decide which table to use based on boolean test flag."""
    if table == "swarm":
        return "test_swarm_table" if test else "swarm_table"
    elif table == "tremor":
        return "test_tremor_table" if test else "tremor_table"
    else:
        return "test_sent_events" if test else "sent_events"


# ---- DB setup ----
def init_db(conn, test=False):
    table_name = resolve_table_name(test)
    table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alarm_id TEXT NOT NULL,
            event_id TEXT,
            volcano TEXT,
            process_time TEXT NOT NULL,   -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
            send_time TEXT NOT NULL   -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
        );
    """

    conn.execute(table_query)
    conn.execute("PRAGMA journal_mode=WAL;")  # optional, improves concurrency


def init_swarm_db(conn, test=False):
    table_name = "test_swarm_table" if test else "swarm_table"

    table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            event_id TEXT PRIMARY KEY NOT NULL,
            time TEXT NOT NULL,   -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            depth REAL NOT NULL,
            mag REAL NOT NULL,
            volcano TEXT NOT NULL
        );
    """
    conn.execute(table_query)
    conn.execute("PRAGMA journal_mode=WAL;")  # optional, improves concurrency


def record_swarm_event_ids(swarm_df, test=False):

    table_name = resolve_table_name(test, table="swarm")
    conn = get_conn(test=test, table="swarm")
    try:
        for i, row in swarm_df.iterrows():
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {table_name} (event_id, time, latitude, longitude, depth, mag, volcano)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.event_id,
                    (iso_utc(row.time.to_pydatetime())),
                    row.latitude,
                    row.longitude,
                    row.depth,
                    row.mag,
                    row.v_name,
                ),
            )
    finally:
        conn.close()


def init_tremor_db(conn, test=False):
    table_name = resolve_table_name(test, table="tremor")
    table_query = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            time TEXT NOT NULL,       -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            depth REAL NOT NULL,
            volcano REAL NOT NULL,
            PRIMARY KEY (time, volcano)
        );
    """
    conn.execute(table_query)
    conn.execute("PRAGMA journal_mode=WAL;")  # optional, improves concurrency


def record_tremor_event_ids(tremor_df, test=False):

    table_name = resolve_table_name(test, table="tremor")
    conn = get_conn(test=test, table="tremor")
    try:
        for i, row in tremor_df.iterrows():
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {table_name} (time, latitude, longitude, depth, volcano)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (iso_utc(row.time.to_pydatetime())),
                    row.latitude,
                    row.longitude,
                    row.depth,
                    row.volcano,
                ),
            )
    finally:
        conn.close()


def get_conn(test=False, table=None):
    db_path = Path(os.environ["DB_FILE"])
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)  # autocommit
    if table == "swarm":
        init_swarm_db(conn, test=test)
    elif table == "tremor":
        init_tremor_db(conn, test=test)
    else:
        init_db(conn, test=test)
    return conn


def record_send(config, T0, volcano=None, event_id=None, test=False):

    process_time = iso_utc(T0.datetime)
    send_time = iso_utc(now_utc())

    if hasattr(config, "volcano_name"):
        volcano = getattr(config, "volcano_name", None)

    if not isinstance(event_id, list):
        event_id = [event_id]

    table_name = resolve_table_name(test)
    conn = get_conn(test=test)
    try:
        for ev_id in event_id:
            conn.execute(
                f"""
                INSERT INTO {table_name} (alarm_id, process_time, send_time, volcano, event_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (config.alarm_name, process_time, send_time, volcano, ev_id)
            )
    finally:
        conn.close()


def can_send(config, volcano="*", T0=None, test=False):

    # Rate-limiting only applies when both knobs are configured.
    has_memory = hasattr(config, "alert_memory") and config.alert_memory is not None
    has_max = hasattr(config, "max_alerts") and config.max_alerts is not None
    if not (has_memory and has_max):
        return True

    if not T0:
        now = now_utc()
    else:
        now = T0.datetime

    cutoff_iso = iso_utc(now - timedelta(seconds=config.alert_memory))
    now_iso = iso_utc(now)

    table_name = resolve_table_name(test)
    base_sql = f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE alarm_id = '{config.alarm_name}'
                AND process_time >= '{cutoff_iso}'
                AND process_time <= '{now_iso}'
                """
    if volcano != "*":
        base_sql += f" AND volcano = '{volcano}'"

    conn = get_conn(test=test)
    try:
        (cnt,) = conn.execute(base_sql).fetchone()

        if cnt < config.max_alerts:
            return True
        else:
            return False

    finally:
        conn.close()


def check_new_event_ids(event_ids, test=False, table=None):
    """
    Return True if ANY of the provided event_ids are NOT already present in the DB.
    Return False if all are already in the DB.
    """
    # Normalize to a unique, non-empty set of strings
    candidate_ids = {str(eid) for eid in event_ids if eid is not None}
    if not candidate_ids:
        return 0, 0  # nothing to check => nothing new

    placeholders = ", ".join("?" for _ in candidate_ids)
    table_name = resolve_table_name(test, table=table)
    conn = get_conn(test=test)  # your existing connection helper
    try:
        rows = conn.execute(
            f"""
            SELECT event_id
            FROM {table_name}
            WHERE event_id IN ({placeholders})
            """,
            tuple(candidate_ids),
        ).fetchall()

        existing = {row[0] for row in rows}
        # If the set difference is non-empty, at least one is new
        return len(candidate_ids - existing), len(existing)
    finally:
        conn.close()


def already_processed(config, evid, test=False):

    table_name = resolve_table_name(test)
    base_sql = f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE alarm_id = '{config.alarm_name}'
                AND event_id = '{evid}'
                """

    conn = get_conn(test=test)
    try:
        (cnt,) = conn.execute(base_sql).fetchone()
        if cnt > 0:
            return True
        else:
            return False
    finally:
        conn.close()


def list_all_alarm_ids(test=False):
    table_name = resolve_table_name(test)
    print(f"Entries for {table_name} table")
    conn = get_conn(test=test)
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT alarm_id
            FROM {table_name}
            ORDER BY alarm_id ASC;
            """
        ).fetchall()

        alarm_ids = [row[0] for row in rows]

        print("All alarm_ids:")
        if not alarm_ids:
            print("  (none)")
        else:
            for aid in alarm_ids:
                print(f"  {aid}")

        return alarm_ids

    finally:
        conn.close()


def filtered_list(query_dict, test=False):

    table_name = resolve_table_name(test)

    headers = ["id", "alarm_id", "process_time", "send_time", "volcano", "event_id"]
    query = f"SELECT {', '.join(headers)} FROM {table_name} WHERE "

    need_and = False
    if "alarm_id" in query_dict.keys():
        a_id = query_dict["alarm_id"]
        query += f"alarm_id = '{a_id}' "
        need_and = True
    if "volcano" in query_dict.keys():
        v_name = query_dict["volcano"]
        if need_and:
            query += f"AND volcano = '{v_name}' "
        else:
            query += f"volcano = '{v_name}' "
        need_and = True
    if "t1" in query_dict.keys():
        t1 = pd.to_datetime(query_dict["t1"]).to_pydatetime()
        t1 = iso_utc(t1)
        if need_and:
            query += f"AND process_time >= '{t1}' "
        else:
            query += f"process_time >= '{t1}' "
        need_and = True
    if "t2" in query_dict.keys():
        t2 = pd.to_datetime(query_dict["t2"]).to_pydatetime()
        t2 = iso_utc(t2)
        if need_and:
            query += f"AND process_time <= '{t2}' "
        else:
            query += f"process_time <= '{t2}' "
        need_and = True
    if "event_id" in query_dict.keys():
        evid = query_dict["event_id"]
        if need_and:
            query += f"AND event_id = {evid} "
        else:
            query += f"event_id = {evid} "
        need_and = True
    
        
    query += "ORDER BY process_time DESC;"

    print(f"Entries for {resolve_table_name(test)} table")
    conn = get_conn(test=test)
    try:
        rows = conn.execute(query).fetchall()
        if not rows:
            print("  (none)")
        else:
            print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))
    finally:
        conn.close()

    return rows


def list_alarm_entries(alarm_id=None, test=False):

    if isinstance(alarm_id, str):
        alarm_ids = [alarm_id]
    else:
        alarm_ids = list_all_alarm_ids()

    headers = ["alarm_id", "process_time", "send_time", "volcano", "event_id"]

    table_name = resolve_table_name(test)
    print(f"Entries for {table_name} table")
    conn = get_conn(test=test)
    try:
        for alarm_id in alarm_ids:
            rows = conn.execute(
                f"""
                SELECT {', '.join(headers)}
                FROM {table_name}
                WHERE alarm_id = '{alarm_id}'
                ORDER BY process_time DESC;
                """
            ).fetchall()

            print(f"\nAlarm entries for: {alarm_id}")
            if not rows:
                print("  (none)")
                continue

            print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))

    finally:
        conn.close()


def remove_alarm_ids(alarm_id, t_start, t_end, test=False):
    if isinstance(t_start, str):
        t_start = pd.to_datetime(t_start)
        t_start = t_start.to_pydatetime()
        t_start = iso_utc(t_start)
    if isinstance(t_end, str):
        t_end = pd.to_datetime(t_end)
        t_end = t_end.to_pydatetime()
        t_end = iso_utc(t_end)

    table_name = resolve_table_name(test)
    try:
        conn = get_conn(test=test)
        conn.execute(
            f"""
            DELETE FROM {table_name}
            WHERE alarm_id = '{alarm_id}'
            AND process_time >= '{t_start}'
            AND process_time <= '{t_end}';
            """
        )
    finally:
        conn.close()

    return


def filter_dataframe(df, id_column="id", test=False, table=None):

    if id_column not in df.columns:
        raise ValueError(f"DataFrame must have an '{id_column}' column")

    # Ensure string comparison consistency (your DB stores TEXT for event_id)
    ids = df[id_column].astype(str)

    table_name = resolve_table_name(test, table=table)
    conn = get_conn(test=test, table=table)

    sql_query = f"SELECT event_id FROM {table_name} WHERE event_id IS NOT NULL"
    try:
        cur = conn.execute(sql_query)
        event_ids_in_db = {row[0] for row in cur.fetchall()}  # build a Python set for fast membership tests

        # Anti-join via boolean mask
        mask_not_in_db = ~ids.isin(event_ids_in_db)
        new_df = df.loc[mask_not_in_db].copy()
        return new_df, df

    finally:
        conn.close()