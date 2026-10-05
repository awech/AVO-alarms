"""
SQLite-backed bookkeeping for alarm sends and event catalogs.

Provides helpers to initialize the alarm database and its tables, record
when alerts are sent, enforce per-alarm rate limits, deduplicate events that
have already been processed, and query or prune the stored history. Separate
``test_*`` tables are used when the ``test`` flag is set so that test runs do
not pollute the production record.

All timestamps are stored as ISO-8601 strings in UTC with a ``Z`` suffix so
they sort lexicographically. The database path is read from the ``DB_FILE``
environment variable.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from tabulate import tabulate


def now_utc():
    """Return the current time as a timezone-aware UTC datetime.

    Returns
    -------
    datetime.datetime
        The current time with ``tzinfo`` set to UTC.
    """
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime):
    """Format a datetime as a sortable ISO-8601 UTC string.

    The datetime is converted to UTC and rendered at second resolution with a
    trailing ``Z`` suffix, producing a lexicographically sortable string.

    Parameters
    ----------
    dt : datetime.datetime
        Datetime to format. May be naive or timezone-aware; it is converted
        to UTC before formatting.

    Returns
    -------
    str
        ISO-8601 timestamp in UTC, e.g. ``"2026-05-07T23:45:00Z"``.
    """
    # ISO-8601 with 'Z' suffix; lexicographically sortable
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def resolve_table_name(test, table=None):
    """Decide which table name to use based on the test flag.

    Parameters
    ----------
    test : bool
        If True, return the name of the corresponding ``test_*`` table.
    table : {None, 'swarm', 'tremor'}, optional
        Which family of table to resolve. ``None`` (the default) resolves the
        sent-events table.

    Returns
    -------
    str
        The resolved table name.
    """
    if table == "swarm":
        return "test_swarm_table" if test else "swarm_table"
    elif table == "tremor":
        return "test_tremor_table" if test else "tremor_table"
    else:
        return "test_sent_events" if test else "sent_events"


# ---- DB setup ----
def init_db(conn, test=False):
    """Create the sent-events table if it does not already exist.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    test : bool, optional
        If True, operate on the test table instead of the production table,
        by default False.
    """
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
    """Create the swarm catalog table if it does not already exist.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    test : bool, optional
        If True, operate on the test swarm table, by default False.
    """
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
    """Insert swarm events into the swarm catalog table.

    Existing rows (matching ``event_id``) are left untouched via
    ``INSERT OR IGNORE``.

    Parameters
    ----------
    swarm_df : pandas.DataFrame
        Swarm events to record. Each row must provide ``event_id``, ``time``
        (a pandas Timestamp), ``latitude``, ``longitude``, ``depth``, ``mag``,
        and ``v_name``.
    test : bool, optional
        If True, write to the test swarm table, by default False.
    """
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
    """Create the tremor catalog table if it does not already exist.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open database connection.
    test : bool, optional
        If True, operate on the test tremor table, by default False.
    """
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
    """Insert tremor events into the tremor catalog table.

    Existing rows (matching the ``(time, volcano)`` primary key) are left
    untouched via ``INSERT OR IGNORE``.

    Parameters
    ----------
    tremor_df : pandas.DataFrame
        Tremor events to record. Each row must provide ``time`` (a pandas
        Timestamp), ``latitude``, ``longitude``, ``depth``, and ``volcano``.
    test : bool, optional
        If True, write to the test tremor table, by default False.
    """
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
    """Open a database connection and ensure the relevant table exists.

    The database path is read from the ``DB_FILE`` environment variable and
    its parent directory is created if necessary. The connection runs in
    autocommit mode.

    Parameters
    ----------
    test : bool, optional
        If True, initialize/target the test tables, by default False.
    table : {None, 'swarm', 'tremor'}, optional
        Which table family to initialize on connect. ``None`` initializes the
        sent-events table.

    Returns
    -------
    sqlite3.Connection
        An open connection with the requested table initialized.
    """
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
    """Record one or more sent alerts in the sent-events table.

    One row is inserted per event id. If the config carries a
    ``volcano_name`` attribute it overrides the ``volcano`` argument.

    Parameters
    ----------
    config : object
        Alarm configuration. Must expose ``alarm_name``; may expose
        ``volcano_name``.
    T0 : obspy.UTCDateTime
        Processing time of the alarm (interpreted as UTC).
    volcano : str, optional
        Volcano name to associate with the send, by default None.
    event_id : str or list of str, optional
        Event id(s) associated with the send. A scalar is wrapped in a list;
        ``None`` records a single row with a null event id.
    test : bool, optional
        If True, write to the test table, by default False.
    """
    process_time = iso_utc(T0.datetime.replace(tzinfo=timezone.utc))
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
    """Check whether another alert is allowed under the rate limit.

    Counts how many alerts for this alarm were recorded within the trailing
    ``config.alert_memory`` seconds and compares against ``config.max_alerts``.
    If either knob is unset, rate limiting is disabled and sending is allowed.

    Parameters
    ----------
    config : object
        Alarm configuration. May expose ``alert_memory`` (seconds) and
        ``max_alerts`` (int); must expose ``alarm_name``.
    volcano : str, optional
        Restrict the count to a single volcano, or ``"*"`` for all volcanoes,
        by default ``"*"``.
    T0 : obspy.UTCDateTime, optional
        Reference "now" for the trailing window. Defaults to the current time.
    test : bool, optional
        If True, query the test table, by default False.

    Returns
    -------
    bool
        True if sending another alert is permitted, False otherwise.
    """
    # Rate-limiting only applies when both knobs are configured.
    has_memory = hasattr(config, "alert_memory") and config.alert_memory is not None
    has_max = hasattr(config, "max_alerts") and config.max_alerts is not None
    if not (has_memory and has_max):
        return True

    now = T0.datetime.replace(tzinfo=timezone.utc) if T0 else now_utc()

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

        return cnt < config.max_alerts

    finally:
        conn.close()


def next_send_after(config, volcano="*", T0=None, test=False):
    """Return when sending will next be allowed after saturating the limit.

    Parameters
    ----------
    config : object
        Alarm configuration. May expose ``alert_memory`` (seconds) and
        ``max_alerts`` (int); must expose ``alarm_name``.
    volcano : str, optional
        Restrict the count to a single volcano, or ``"*"`` for all volcanoes,
        by default ``"*"``.
    T0 : obspy.UTCDateTime, optional
        Reference "now" for the trailing window. Defaults to the current time.
    test : bool, optional
        If True, query the test table, by default False.

    Returns
    -------
    datetime.datetime or None
        The earliest UTC datetime at which a new alert will be allowed again,
        or ``None`` if rate limiting is not configured or the limit will not
        be saturated after the current send.
    """
    has_memory = hasattr(config, "alert_memory") and config.alert_memory is not None
    has_max = hasattr(config, "max_alerts") and config.max_alerts is not None
    if not (has_memory and has_max):
        return None

    now = T0.datetime.replace(tzinfo=timezone.utc) if T0 else now_utc()
    cutoff_iso = iso_utc(now - timedelta(seconds=config.alert_memory))
    now_iso = iso_utc(now)

    table_name = resolve_table_name(test)
    base_sql = f"""
                SELECT process_time FROM {table_name}
                WHERE alarm_id = '{config.alarm_name}'
                AND process_time >= '{cutoff_iso}'
                AND process_time <= '{now_iso}'
                """
    if volcano != "*":
        base_sql += f" AND volcano = '{volcano}'"
    base_sql += " ORDER BY process_time ASC"

    conn = get_conn(test=test)
    try:
        rows = conn.execute(base_sql).fetchall()
        # After the current send, count will be len(rows) + 1.
        # Suppression kicks in when count >= max_alerts.
        if len(rows) + 1 >= config.max_alerts:
            oldest = datetime.fromisoformat(rows[0][0].replace("Z", "+00:00"))
            return oldest + timedelta(seconds=config.alert_memory)
        return None
    finally:
        conn.close()


def check_new_event_ids(event_ids, test=False, table=None):
    """Count how many of the given event ids are new versus already stored.

    Parameters
    ----------
    event_ids : iterable
        Candidate event ids. ``None`` values are ignored and duplicates are
        collapsed before checking.
    test : bool, optional
        If True, query the test table, by default False.
    table : {None, 'swarm', 'tremor'}, optional
        Which table family to query, by default None (sent-events).

    Returns
    -------
    tuple of int
        ``(num_new, num_existing)`` where ``num_new`` is the count of
        candidate ids not present in the database and ``num_existing`` is the
        count already present. Returns ``(0, 0)`` when there are no candidates.
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
    """Check whether an event has already been processed for this alarm.

    Parameters
    ----------
    config : object
        Alarm configuration exposing ``alarm_name``.
    evid : str
        Event id to look up.
    test : bool, optional
        If True, query the test table, by default False.

    Returns
    -------
    bool
        True if a matching ``(alarm_id, event_id)`` row exists, else False.
    """
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
        return cnt > 0
    finally:
        conn.close()


def list_all_alarm_ids(test=False):
    """Print and return the distinct alarm ids present in the table.

    Parameters
    ----------
    test : bool, optional
        If True, query the test table, by default False.

    Returns
    -------
    list of str
        Distinct ``alarm_id`` values, sorted ascending.
    """
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
    """Query sent-events rows matching a set of filters and print them.

    Parameters
    ----------
    query_dict : dict
        Optional filter keys, any of which may be present: ``alarm_id``,
        ``volcano``, ``t1`` (process_time lower bound, UTC), ``t2``
        (process_time upper bound, UTC), and ``event_id``.
    test : bool, optional
        If True, query the test table, by default False.

    Returns
    -------
    list of tuple
        The matching rows, ordered by ``process_time`` descending.
    """
    table_name = resolve_table_name(test)

    headers = ["id", "alarm_id", "process_time", "send_time", "volcano", "event_id"]
    query = f"SELECT {', '.join(headers)} FROM {table_name} WHERE "

    need_and = False
    if "alarm_id" in query_dict:
        a_id = query_dict["alarm_id"]
        query += f"alarm_id = '{a_id}' "
        need_and = True
    if "volcano" in query_dict:
        v_name = query_dict["volcano"]
        if need_and:
            query += f"AND volcano = '{v_name}' "
        else:
            query += f"volcano = '{v_name}' "
        need_and = True
    if "t1" in query_dict:
        # Time bounds are UTC (per the list-alerts CLI). Parse as UTC so a naive
        # string isn't reinterpreted as system-local by iso_utc's astimezone().
        t1 = pd.to_datetime(query_dict["t1"], utc=True).to_pydatetime()
        t1 = iso_utc(t1)
        if need_and:
            query += f"AND process_time >= '{t1}' "
        else:
            query += f"process_time >= '{t1}' "
        need_and = True
    if "t2" in query_dict:
        t2 = pd.to_datetime(query_dict["t2"], utc=True).to_pydatetime()
        t2 = iso_utc(t2)
        if need_and:
            query += f"AND process_time <= '{t2}' "
        else:
            query += f"process_time <= '{t2}' "
        need_and = True
    if "event_id" in query_dict:
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
    """Print all stored entries, grouped by alarm id.

    Parameters
    ----------
    alarm_id : str, optional
        A single alarm id to list. If omitted, every distinct alarm id in the
        table is listed.
    test : bool, optional
        If True, query the test table, by default False.
    """
    if isinstance(alarm_id, str):
        alarm_ids = [alarm_id]
    else:
        alarm_ids = list_all_alarm_ids()

    headers = ["alarm_id", "process_time", "send_time", "volcano", "event_id"]

    table_name = resolve_table_name(test)
    print(f"Entries for {table_name} table")
    conn = get_conn(test=test)
    try:
        for i_alarm_id in alarm_ids:
            rows = conn.execute(
                f"""
                SELECT {', '.join(headers)}
                FROM {table_name}
                WHERE alarm_id = '{i_alarm_id}'
                ORDER BY process_time DESC;
                """
            ).fetchall()

            print(f"\nAlarm entries for: {i_alarm_id}")
            if not rows:
                print("  (none)")
                continue

            print(tabulate(rows, headers=headers, tablefmt="fancy_grid"))

    finally:
        conn.close()


def remove_alarm_ids(alarm_id, t_start, t_end, test=False):
    """Delete sent-events rows for an alarm within a time range.

    Parameters
    ----------
    alarm_id : str
        Alarm id whose rows should be removed.
    t_start : str or datetime.datetime
        Inclusive lower bound on ``process_time`` (interpreted as UTC).
    t_end : str or datetime.datetime
        Inclusive upper bound on ``process_time`` (interpreted as UTC).
    test : bool, optional
        If True, operate on the test table, by default False.
    """
    # Time bounds are UTC; parse as UTC so a naive string isn't shifted by
    # iso_utc's astimezone() on a non-UTC host.
    if isinstance(t_start, str):
        t_start = iso_utc(pd.to_datetime(t_start, utc=True).to_pydatetime())
    if isinstance(t_end, str):
        t_end = iso_utc(pd.to_datetime(t_end, utc=True).to_pydatetime())

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


def remove_catalog_entries(t_start, t_end, table, test=False):
    """Remove entries from the tremor or swarm catalog within a time range.

    Parameters
    ----------
    t_start : str or datetime
        Start of time range to delete.
    t_end : str or datetime
        End of time range to delete.
    table : {'tremor', 'swarm'}
        Which catalog table to target.
    test : bool, optional
        Use test tables if True, by default False.

    Raises
    ------
    ValueError
        If ``table`` is not ``'tremor'`` or ``'swarm'``.
    """
    if table not in ("tremor", "swarm"):
        raise ValueError(f"table must be 'tremor' or 'swarm', got '{table}'")

    # Time bounds are UTC; parse as UTC (see remove_alarm_ids).
    if isinstance(t_start, str):
        t_start = iso_utc(pd.to_datetime(t_start, utc=True).to_pydatetime())
    if isinstance(t_end, str):
        t_end = iso_utc(pd.to_datetime(t_end, utc=True).to_pydatetime())

    table_name = resolve_table_name(test, table=table)
    conn = get_conn(test=test, table=table)
    try:
        conn.execute(
            f"""
            DELETE FROM {table_name}
            WHERE time >= '{t_start}'
            AND time <= '{t_end}';
            """
        )
    finally:
        conn.close()


def filter_dataframe(df, id_column="id", test=False, table=None):
    """Split a DataFrame into rows whose ids are new versus all rows.

    Performs an anti-join against the stored ``event_id`` values, treating ids
    as strings for comparison.

    Parameters
    ----------
    df : pandas.DataFrame
        Input events. Must contain the column named by ``id_column``.
    id_column : str, optional
        Column holding candidate event ids, by default ``"id"``.
    test : bool, optional
        If True, query the test table, by default False.
    table : {None, 'swarm', 'tremor'}, optional
        Which table family to compare against, by default None (sent-events).

    Returns
    -------
    tuple of pandas.DataFrame
        ``(new_df, df)`` where ``new_df`` contains only rows whose ids are not
        already present in the database and ``df`` is the original input.

    Raises
    ------
    ValueError
        If ``id_column`` is not a column of ``df``.
    """
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