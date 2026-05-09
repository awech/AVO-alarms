import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from tabulate import tabulate


# ---- Config ----
from dotenv import load_dotenv
load_dotenv()
DB_PATH = Path(os.environ["DB_FILE"])


def now_utc():
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime):
    # ISO-8601 with 'Z' suffix; lexicographically sortable
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


# ---- DB setup ----
def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alarm_id TEXT NOT NULL,
            event_id TEXT,
            volcano TEXT,
            process_time TEXT NOT NULL,   -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
            send_time TEXT NOT NULL,   -- ISO-8601 UTC, e.g., 2026-05-07T23:45:00Z
            test BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)
    conn.execute("PRAGMA journal_mode=WAL;")  # optional, improves concurrency

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)  # autocommit
    init_db(conn)
    return conn


def record_send(config, T0, volcano=None, event_id=None, test=False):

    process_time = iso_utc(T0.datetime)
    send_time = iso_utc(now_utc())

    if hasattr(config, "VOLCANO_NAME"):
        volcano = config.VOLCANO_NAME

    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        conn.execute(
            """
            INSERT INTO sent_events(alarm_id, process_time, send_time, volcano, event_id, test)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (config.alarm_name, process_time, send_time, volcano, event_id, test),
        )
        conn.execute("COMMIT;")
    finally:
        conn.close()


def can_send(config, volcano="*", T0=None):

    WINDOW_SECONDS = 3600
    N_ALERTS = 3

    if hasattr(config, "ALERT_MEMORY"):
        WINDOW_SECONDS = config.ALERT_MEMORY
    
    if hasattr(config, "MAX_ALERTS"):
        N_ALERTS = config.MAX_ALERTS

    if not T0:
        now = now_utc()
    else:
        now = T0.datetime
        
    cutoff_iso = iso_utc(now - timedelta(seconds=WINDOW_SECONDS))
    now_iso = iso_utc(now)

    base_sql = f"""
            SELECT COUNT(*)
            FROM sent_events
            WHERE alarm_id = '{config.alarm_name}'
            AND process_time >= '{cutoff_iso}'
            AND process_time <= '{now_iso}'
        """
    if volcano != "*":
        base_sql += f" AND volcano = '{volcano}'"

    conn = get_conn()
    try:
        (cnt,) = conn.execute(base_sql).fetchone()

        if cnt < N_ALERTS:
            return True
        else:
            return False
    except Exception:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def check_new_event_ids(event_ids):
    """
    Return True if ANY of the provided event_ids are NOT already present in the DB.
    Return False if all are already in the DB.
    """
    # Normalize to a unique, non-empty set of strings
    candidate_ids = {str(eid) for eid in event_ids if eid is not None}
    if not candidate_ids:
        return 0, 0  # nothing to check => nothing new

    placeholders = ", ".join("?" for _ in candidate_ids)
    conn = get_conn()  # your existing connection helper
    try:
        rows = conn.execute(
            f"""
            SELECT event_id
            FROM sent_events
            WHERE event_id IN ({placeholders})
            """,
            tuple(candidate_ids),
        ).fetchall()

        existing = {row[0] for row in rows}
        # If the set difference is non-empty, at least one is new
        return len(candidate_ids - existing), len(existing)
    finally:
        conn.close()


def already_processed(config, evid):

    base_sql = f"""
            SELECT COUNT(*)
            FROM sent_events
            WHERE alarm_id = '{config.alarm_name}'
            AND event_id = '{evid}'
        """

    conn = get_conn()
    try:
        (cnt,) = conn.execute(base_sql).fetchone()
        if cnt > 0:
            return True
        else:
            return False
    except Exception:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def list_all_alarm_ids():
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT alarm_id
            FROM sent_events
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


def filtered_list(query_dict):

    headers = ["id", "alarm_id", "process_time", "send_time", "volcano", "event_id", "test"]
    query = f"SELECT {', '.join(headers)} FROM sent_events WHERE "

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
    if "test" in query_dict.keys():
        test_flag = query_dict["test"]
        if need_and:
            query += f"AND test = {test_flag} "
        else:
            query += f"test = {test_flag} "
        need_and = True
    if "event_id" in query_dict.keys():
        evid = query_dict["event_id"]
        if need_and:
            query += f"AND event_id = {evid} "
        else:
            query += f"event_id = {evid} "
        need_and = True
    
        
    query += "ORDER BY process_time DESC;"

    conn = get_conn()
    try:
        rows = conn.execute(query
        ).fetchall()

        if not rows:
            print("  (none)")
        else:
            print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))

    finally:
        conn.close()

    return rows


def list_alarm_entries(alarm_id=None):

    if isinstance(alarm_id, str):
        alarm_ids = [alarm_id]
    else:
        alarm_ids = list_all_alarm_ids()

    headers = ["alarm_id", "process_time", "send_time", "volcano", "event_id", "test"]
    conn = get_conn()
    try:
        for alarm_id in alarm_ids:
            rows = conn.execute(
                f"""
                SELECT {', '.join(headers)}
                FROM sent_events
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


def remove_alarm_ids(alarm_id, t_start, t_end):
    if isinstance(t_start, str):
        t_start = pd.to_datetime(t_start)
        t_start = t_start.to_pydatetime()
        t_start = iso_utc(t_start)
    if isinstance(t_end, str):
        t_end = pd.to_datetime(t_end)
        t_end = t_end.to_pydatetime()
        t_end = iso_utc(t_end)

    try:
        conn = get_conn()
        conn.execute(
            f"""
            DELETE FROM sent_events
            WHERE alarm_id = '{alarm_id}'
            AND process_time >= '{t_start}'
            AND process_time <= '{t_end}';
            """
        )
    finally:
        conn.close()

    return