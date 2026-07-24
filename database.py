import sqlite3
import json
import os
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')
# Safe section accessor — if config.ini is absent (AWS env-var-only deployments)
# this falls back to an empty dict so .get() returns '' gracefully.
_app_cfg = config['APP'] if config.has_section('APP') else {}
# Env var (injected by systemd) takes priority over config.ini
DB_URI = os.environ.get('DATABASE_URI') or _app_cfg.get('database_uri', 'sqlite:///database.db')

IS_POSTGRES = DB_URI.startswith('postgres')
if IS_POSTGRES:
    import pg8000.dbapi
    import ssl
    from urllib.parse import urlparse, parse_qs

def get_db_connection():
    if IS_POSTGRES:
        parsed = urlparse(DB_URI)
        # pg8000 does not parse sslmode from the URL automatically.
        # Build an ssl_context if sslmode=require is in the query string.
        qs = parse_qs(parsed.query)
        ssl_ctx = None
        if qs.get('sslmode', [''])[0] in ('require', 'verify-ca', 'verify-full'):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        conn = pg8000.dbapi.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path.lstrip('/'),
            ssl_context=ssl_ctx,
            timeout=10
        )
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(DB_URI.replace('sqlite:///', ''), timeout=30.0) # Increase timeout
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL;')
        return conn

def exec_query(conn, query, params=(), fetchone=False, fetchall=False):
    """Helper to execute queries compatibly across SQLite and Postgres."""
    if IS_POSTGRES:
        query = query.replace('?', '%s')
        
        # Dialect translation
        if 'INTEGER PRIMARY KEY AUTOINCREMENT' in query:
            query = query.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            
        if 'INSERT OR REPLACE INTO global_settings' in query:
            query = query.replace('INSERT OR REPLACE INTO global_settings', 'INSERT INTO global_settings')
            if 'ON CONFLICT' not in query:
                query += ' ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value'
                
        if 'INSERT OR REPLACE INTO geocode_cache' in query:
            query = query.replace('INSERT OR REPLACE INTO geocode_cache', 'INSERT INTO geocode_cache')
            if 'ON CONFLICT' not in query:
                query += ' ON CONFLICT(address) DO UPDATE SET lat=EXCLUDED.lat, lng=EXCLUDED.lng'

    if IS_POSTGRES:
        c = conn.cursor()
    else:
        c = conn.cursor()
        
    c.execute(query, params)
    
    if IS_POSTGRES:
        if c.description:
            columns = [col[0] for col in c.description]
            if fetchone:
                row = c.fetchone()
                return dict(zip(columns, row)) if row else None
            if fetchall:
                return [dict(zip(columns, row)) for row in c.fetchall()]
        return c
    else:
        if fetchone:
            return c.fetchone()
        if fetchall:
            return c.fetchall()
        return c

def init_db():
    conn = get_db_connection()
    
    # Check current schema version
    exec_query(conn, "CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)")
    row = exec_query(conn, "SELECT value FROM global_settings WHERE key = 'schema_version'", fetchone=True)
    schema_version = int(row['value']) if row else 0
    
    # Version 2 is the multi-tenant version
    if schema_version < 2:
        print("Migrating to schema version 2 (Multi-tenancy reset)...")
        # The user requested a clean start to fix constraint issues
        exec_query(conn, "DROP TABLE IF EXISTS module_config")
        exec_query(conn, "DROP TABLE IF EXISTS module_records")
        exec_query(conn, "DROP TABLE IF EXISTS module_config_old")
        exec_query(conn, "DROP TABLE IF EXISTS module_records_old")
        
        # Update version
        exec_query(conn, "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", ('schema_version', '2'))

    # Table for Module Configuration (Clean Slate)
    exec_query(conn, '''
        CREATE TABLE IF NOT EXISTS module_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            module_name TEXT NOT NULL,
            location_type TEXT NOT NULL,
            field_mappings TEXT NOT NULL,
            marker_color TEXT NOT NULL,
            marker_icon TEXT NOT NULL DEFAULT 'pin',
            is_shared INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, module_name)
        )
    ''')

    if schema_version < 3:
        print("Migrating to schema version 3 (Shared Configs)...")
        try:
            if IS_POSTGRES:
                cols_data = exec_query(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='module_config'", fetchall=True)
                cols = [col['column_name'] for col in cols_data]
            else:
                cols_data = exec_query(conn, "PRAGMA table_info(module_config)", fetchall=True)
                cols = [col[1] for col in cols_data]

            if 'is_shared' not in cols:
                exec_query(conn, "ALTER TABLE module_config ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 0")
        except Exception as e:
            print(f"Migration error: {e}")
        exec_query(conn, "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", ('schema_version', '3'))

    # Table for Cached Zoho Records (Clean Slate)
    exec_query(conn, '''
        CREATE TABLE IF NOT EXISTS module_records (
            id TEXT,
            user_id TEXT NOT NULL,
            module_name TEXT,
            name TEXT,
            lat REAL,
            lng REAL,
            color TEXT,
            record_data TEXT,
            PRIMARY KEY (id, module_name, user_id)
        )
    ''')

    # Schema v4: add franchise_id column for global cache filtering
    if schema_version < 4:
        print("Migrating to schema version 4 (Global Nightly Cache)...")
        try:
            if IS_POSTGRES:
                cols_data = exec_query(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='module_records'", fetchall=True)
                cols = [col['column_name'] for col in cols_data]
            else:
                cols_data = exec_query(conn, "PRAGMA table_info(module_records)", fetchall=True)
                cols = [col[1] for col in cols_data]

            if 'franchise_id' not in cols:
                exec_query(conn, "ALTER TABLE module_records ADD COLUMN franchise_id TEXT")
                print("  Added franchise_id column to module_records.")
        except Exception as e:
            print(f"Migration v4 error: {e}")
        # Create index for efficient global cache queries
        try:
            exec_query(conn, "CREATE INDEX IF NOT EXISTS idx_global_franchise ON module_records(user_id, franchise_id)")
        except Exception:
            pass
        exec_query(conn, "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", ('schema_version', '4'))

    # Table for Geocode Caching (Keep this, it's expensive to refill)
    exec_query(conn, '''
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lng REAL
        )
    ''')

    # Performance Monitoring Logs table
    exec_query(conn, '''
        CREATE TABLE IF NOT EXISTS performance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            endpoint TEXT NOT NULL,
            response_time_ms REAL NOT NULL,
            record_count INTEGER DEFAULT 0,
            user_id TEXT,
            status_code INTEGER DEFAULT 200
        )
    ''')

    # Ensure unique index exists for safety and performance indexes
    try:
        exec_query(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_module ON module_config (user_id, module_name)")
        exec_query(conn, "CREATE INDEX IF NOT EXISTS idx_mod_rec_user_module ON module_records(user_id, module_name)")
        exec_query(conn, "CREATE INDEX IF NOT EXISTS idx_mod_rec_spatial ON module_records(user_id, lat, lng)")
        exec_query(conn, "CREATE INDEX IF NOT EXISTS idx_perf_logs_ts ON performance_logs(timestamp)")
        exec_query(conn, "CREATE INDEX IF NOT EXISTS idx_perf_logs_ep ON performance_logs(endpoint)")
    except Exception as e:
        print(f"Index creation notice: {e}")

    # Prune old performance logs (older than 7 days)
    import time
    try:
        cutoff = time.time() - (7 * 86400)
        exec_query(conn, "DELETE FROM performance_logs WHERE timestamp < ?", (cutoff,))
    except Exception as e:
        print(f"Perf log prune notice: {e}")

    conn.commit()
    conn.close()

def get_global_setting(key, default=None):
    conn = get_db_connection()
    row = exec_query(conn, 'SELECT value FROM global_settings WHERE key = ?', (key,), fetchone=True)
    conn.close()
    if row:
        return row['value']
    return default

def set_global_setting(key, value):
    conn = get_db_connection()
    exec_query(conn, '''
        INSERT INTO global_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
    ''', (key, str(value)))
    conn.commit()
    conn.close()

def get_all_module_configs(user_id):
    conn = get_db_connection()
    configs = exec_query(conn, 'SELECT * FROM module_config WHERE user_id = ?', (str(user_id),), fetchall=True)
    conn.close()
    
    results = []
    for row in configs:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_module_config(user_id, module_name):
    conn = get_db_connection()
    row = exec_query(conn, 'SELECT * FROM module_config WHERE user_id = ? AND module_name = ?', (str(user_id), module_name), fetchone=True)
    conn.close()
    if row:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        return r
    return None

def save_module_config(user_id, module_name, location_type, field_mappings, marker_color, marker_icon='pin', is_shared=False):
    conn = get_db_connection()
    field_mappings_str = json.dumps(field_mappings)
    
    exec_query(conn, '''
        INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon, is_shared)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, module_name) DO UPDATE SET
            location_type=EXCLUDED.location_type,
            field_mappings=EXCLUDED.field_mappings,
            marker_color=EXCLUDED.marker_color,
            marker_icon=EXCLUDED.marker_icon,
            is_shared=EXCLUDED.is_shared
    ''', (str(user_id), module_name, location_type, field_mappings_str, marker_color, marker_icon, 1 if is_shared else 0))
    
    conn.commit()
    conn.close()

def get_shared_configs():
    conn = get_db_connection()
    configs = exec_query(conn, 'SELECT * FROM module_config WHERE is_shared = 1', fetchall=True)
    conn.close()
    
    results = []
    for row in configs:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_effective_configs(user_id, is_admin=False):
    conn = get_db_connection()
    if not is_admin:
        # Standard users ONLY get configurations set and shared by admins.
        # Flushes any old private configs they might have to enforce the admin shared defaults.
        try:
            exec_query(conn, 'DELETE FROM module_config WHERE user_id = ?', (str(user_id),))
            conn.commit()
        except Exception:
            conn.rollback()

        shared = exec_query(conn, 'SELECT * FROM module_config WHERE is_shared = 1', fetchall=True)
        conn.close()
        results = []
        for row in shared:
            r = dict(row)
            r['field_mappings'] = json.loads(r['field_mappings'])
            results.append(r)
        return results
    else:
        # Admin gets their own configs, plus any shared configs they don't own
        own = exec_query(conn, 'SELECT * FROM module_config WHERE user_id = ?', (str(user_id),), fetchall=True)
        own_modules = {r['module_name'] for r in own}
        shared = exec_query(conn, 'SELECT * FROM module_config WHERE is_shared = 1 AND user_id != ?', (str(user_id),), fetchall=True)
        conn.close()
        
        results = []
        for row in list(own) + [r for r in shared if r['module_name'] not in own_modules]:
            r = dict(row)
            r['field_mappings'] = json.loads(r['field_mappings'])
            results.append(r)
        return results

def delete_module_config(user_id, module_name):
    conn = get_db_connection()
    exec_query(conn, 'DELETE FROM module_config WHERE user_id = ? AND module_name = ?', (str(user_id), module_name))
    conn.commit()
    conn.close()

def get_cached_geocode(address, conn=None):
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    row = exec_query(conn, 'SELECT lat, lng FROM geocode_cache WHERE address = ?', (address,), fetchone=True)
    if should_close:
        conn.close()
    if row:
        return {'lat': row['lat'], 'lng': row['lng']}
    return None

def set_cached_geocode(address, lat, lng, conn=None):
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    exec_query(conn, '''
        INSERT OR REPLACE INTO geocode_cache (address, lat, lng)
        VALUES (?, ?, ?)
    ''', (address, lat, lng))
    if not IS_POSTGRES:
        conn.commit()
    if should_close:
        conn.close()

def save_module_record(user_id, id, module_name, name, lat, lng, color, record_data):
    save_module_records_batch(user_id, [(id, module_name, name, lat, lng, color, record_data)])

def save_module_records_batch(user_id, records):
    conn = get_db_connection()
    try:
        exec_query(conn, 'BEGIN TRANSACTION')
        for rec in records:
            franchise_id = None
            if len(rec) == 8:
                id, module_name, name, lat, lng, color, record_data, franchise_id = rec
            else:
                id, module_name, name, lat, lng, color, record_data = rec
            exec_query(conn, '''
                INSERT INTO module_records (user_id, id, module_name, name, lat, lng, color, record_data, franchise_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, module_name, user_id) DO UPDATE SET
                    name=EXCLUDED.name,
                    lat=EXCLUDED.lat,
                    lng=EXCLUDED.lng,
                    color=EXCLUDED.color,
                    record_data=EXCLUDED.record_data,
                    franchise_id=EXCLUDED.franchise_id
            ''', (str(user_id), str(id), module_name, name, lat, lng, color, json.dumps(record_data), franchise_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_records_in_bounds(user_id, min_lat, max_lat, min_lng, max_lng):
    conn = get_db_connection()
    if min_lng > max_lng:
        query = '''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND (lng >= ? OR lng <= ?)
            LIMIT 5000
        '''
        rows = exec_query(conn, query, (str(user_id), min_lat, max_lat, min_lng, max_lng), fetchall=True)
    else:
        query = '''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND lng >= ? AND lng <= ?
            LIMIT 5000
        '''
        rows = exec_query(conn, query, (str(user_id), min_lat, max_lat, min_lng, max_lng), fetchall=True)
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r['record_data'] = json.loads(r['record_data'])
        results.append(r)
    return results

def clear_module_records(user_id, module_name):
    conn = get_db_connection()
    exec_query(conn, 'DELETE FROM module_records WHERE user_id = ? AND module_name = ?', (str(user_id), module_name))
    conn.commit()
    conn.close()

# ── Global Nightly Cache (user_id = '__global__') ─────────────────────────────

GLOBAL_USER = '__global__'

def clear_global_module_records(module_name):
    """Wipe the nightly-synced global cache for a single module."""
    conn = get_db_connection()
    exec_query(conn, 'DELETE FROM module_records WHERE user_id = ? AND module_name = ?',
               (GLOBAL_USER, module_name))
    conn.commit()
    conn.close()

def delete_stale_global_records(module_name, active_ids):
    """Delete all global cache records for a module that are NOT in the active_ids list."""
    conn = get_db_connection()
    active_ids_set = {str(aid) for aid in active_ids}
    try:
        if not active_ids_set:
            exec_query(conn, "DELETE FROM module_records WHERE user_id = ? AND module_name = ?", (GLOBAL_USER, module_name))
        else:
            # Select current database record IDs for this module to find candidates for deletion
            rows = exec_query(conn, "SELECT id FROM module_records WHERE user_id = ? AND module_name = ?", (GLOBAL_USER, module_name), fetchall=True)
            db_ids = {str(row['id']) for row in rows}
            stale_ids = db_ids - active_ids_set
            
            if stale_ids:
                stale_ids_list = list(stale_ids)
                chunk_size = 500
                if not IS_POSTGRES:
                    exec_query(conn, 'BEGIN TRANSACTION')
                for i in range(0, len(stale_ids_list), chunk_size):
                    chunk = stale_ids_list[i:i+chunk_size]
                    placeholders = ', '.join(['?' for _ in chunk])
                    exec_query(conn, f"DELETE FROM module_records WHERE user_id = ? AND module_name = ? AND id IN ({placeholders})", (GLOBAL_USER, module_name) + tuple(chunk))
                if not IS_POSTGRES:
                    conn.commit()
    except Exception as e:
        if not IS_POSTGRES:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        conn.close()

def get_global_records_by_module(module_name):
    """Retrieve all global cache records for a specific module."""
    conn = get_db_connection()
    rows = exec_query(conn, "SELECT id, lat, lng, color, record_data, franchise_id, name FROM module_records WHERE user_id = ? AND module_name = ?", (GLOBAL_USER, module_name), fetchall=True)
    conn.close()
    
    results = []
    for row in rows:
        r = dict(row)
        r['record_data'] = json.loads(r['record_data'])
        results.append(r)
    return results

def save_global_records_batch(records):

    """Batch-save records into the global cache (user_id='__global__').
    Each record is a tuple: (id, module_name, name, lat, lng, color, record_data_dict, franchise_id)
    """
    conn = get_db_connection()
    try:
        exec_query(conn, 'BEGIN TRANSACTION')
        for rec in records:
            rid, module_name, name, lat, lng, color, record_data, franchise_id = rec
            exec_query(conn, '''
                INSERT INTO module_records
                    (user_id, id, module_name, name, lat, lng, color, record_data, franchise_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, module_name, user_id) DO UPDATE SET
                    name=EXCLUDED.name,
                    lat=EXCLUDED.lat,
                    lng=EXCLUDED.lng,
                    color=EXCLUDED.color,
                    record_data=EXCLUDED.record_data,
                    franchise_id=EXCLUDED.franchise_id
            ''', (GLOBAL_USER, str(rid), module_name, name, lat, lng, color,
                  json.dumps(record_data), franchise_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_records_in_bounds_global(franchise_ids, min_lat, max_lat, min_lng, max_lng, is_admin=False):
    """Query the global cache. Admins see all; non-admins filtered by their franchise IDs.
    Returns [] if global cache is empty (caller should fall back to per-user records).
    """
    if not is_admin and (franchise_ids is None or len(franchise_ids) == 0):
        return []  # User has no franchises or list is unknown → no records (secure by default)

    conn = get_db_connection()

    # Build franchise IN clause
    if is_admin or franchise_ids is None:
        franchise_filter = ""
        franchise_params = ()
    else:
        placeholders = ', '.join(['?' for _ in franchise_ids])
        franchise_filter = f"AND franchise_id IN ({placeholders})"
        franchise_params = tuple(franchise_ids)

    base_params = (GLOBAL_USER, min_lat, max_lat)
    if min_lng > max_lng:
        query = f'''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND (lng >= ? OR lng <= ?)
            {franchise_filter}
            LIMIT 5000
        '''
        params = base_params + (min_lng, max_lng) + franchise_params
    else:
        query = f'''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND lng >= ? AND lng <= ?
            {franchise_filter}
            LIMIT 5000
        '''
        params = base_params + (min_lng, max_lng) + franchise_params

    rows = exec_query(conn, query, params, fetchall=True)
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r['record_data'] = json.loads(r['record_data'])
        results.append(r)
    return results

def get_global_record_counts():
    """Return {module_name: count} for the global nightly cache."""
    conn = get_db_connection()
    rows = exec_query(conn,
        "SELECT module_name, COUNT(*) as cnt FROM module_records WHERE user_id = ? GROUP BY module_name",
        (GLOBAL_USER,), fetchall=True)
    conn.close()
    return {row['module_name']: row['cnt'] for row in rows}

# ── Shared helpers ────────────────────────────────────────────────────────────

def get_all_global_settings():
    """Return all rows from global_settings as a list of dicts."""
    conn = get_db_connection()
    rows = exec_query(conn, 'SELECT key, value FROM global_settings', fetchall=True)
    conn.close()
    return [dict(r) for r in rows]

def get_all_module_configs_all_users():
    """Return every module_config row (all users) as a list of dicts with field_mappings parsed."""
    conn = get_db_connection()
    rows = exec_query(conn, 'SELECT * FROM module_config', fetchall=True)
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_hidden_records(user_id):
    """Query and return a set of (id, module_name) tuples representing records that the user has marked as hidden (NULL lat/lng)."""
    conn = get_db_connection()
    rows = exec_query(conn, 'SELECT id, module_name FROM module_records WHERE user_id = ? AND (lat IS NULL OR lng IS NULL)', (str(user_id),), fetchall=True)
    conn.close()
    return {(r['id'], r['module_name']) for r in rows}


def log_performance_metric(endpoint, response_time_ms, record_count=0, user_id=None, status_code=200):
    """Log performance metrics for monitoring (safe, non-blocking fallback)."""
    try:
        import time
        conn = get_db_connection()
        exec_query(conn, '''
            INSERT INTO performance_logs (timestamp, endpoint, response_time_ms, record_count, user_id, status_code)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (time.time(), str(endpoint), float(response_time_ms), int(record_count or 0), str(user_id or ''), int(status_code or 200)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to log perf metric: {e}")


def get_performance_stats(range_hours=24):
    """Aggregate performance statistics for the last 24h or 7d (168h)."""
    import time
    import datetime
    now = time.time()
    since = now - (float(range_hours) * 3600.0)

    conn = get_db_connection()
    try:
        # Overview summary
        row = exec_query(conn, '''
            SELECT COUNT(*) as total_requests,
                   AVG(response_time_ms) as avg_latency,
                   MAX(response_time_ms) as max_latency,
                   SUM(record_count) as total_records
            FROM performance_logs
            WHERE timestamp >= ?
        ''', (since,), fetchone=True)

        overview = {
            'total_requests': int(row['total_requests']) if row and row['total_requests'] else 0,
            'avg_latency_ms': round(float(row['avg_latency']), 2) if row and row['avg_latency'] else 0.0,
            'max_latency_ms': round(float(row['max_latency']), 2) if row and row['max_latency'] else 0.0,
            'total_records': int(row['total_records']) if row and row['total_records'] else 0
        }

        # Breakdown by endpoint
        ep_rows = exec_query(conn, '''
            SELECT endpoint,
                   COUNT(*) as calls,
                   AVG(response_time_ms) as avg_ms,
                   MAX(response_time_ms) as max_ms
            FROM performance_logs
            WHERE timestamp >= ?
            GROUP BY endpoint
            ORDER BY calls DESC
            LIMIT 15
        ''', (since,), fetchall=True)

        endpoints = []
        for r in ep_rows or []:
            endpoints.append({
                'endpoint': r['endpoint'],
                'calls': int(r['calls']),
                'avg_ms': round(float(r['avg_ms']), 2),
                'max_ms': round(float(r['max_ms']), 2)
            })

        # Time series interval buckets (12 buckets)
        num_buckets = 12
        bucket_size = (now - since) / num_buckets
        time_series = []
        for i in range(num_buckets):
            b_start = since + (i * bucket_size)
            b_end = b_start + bucket_size
            b_row = exec_query(conn, '''
                SELECT COUNT(*) as cnt, AVG(response_time_ms) as avg_ms
                FROM performance_logs
                WHERE timestamp >= ? AND timestamp < ?
            ''', (b_start, b_end), fetchone=True)

            dt = datetime.datetime.fromtimestamp(b_start)
            label = dt.strftime('%H:%M') if range_hours <= 24 else dt.strftime('%m/%d %H:%M')
            time_series.append({
                'label': label,
                'requests': int(b_row['cnt']) if b_row and b_row['cnt'] else 0,
                'avg_ms': round(float(b_row['avg_ms']), 2) if b_row and b_row['avg_ms'] else 0.0
            })

        # Total cached records summary by module
        mod_counts = exec_query(conn, '''
            SELECT module_name, COUNT(*) as record_count
            FROM module_records
            GROUP BY module_name
        ''', fetchall=True)
        cached_modules = [{'module': r['module_name'], 'count': r['record_count']} for r in mod_counts or []]

        return {
            'range_hours': range_hours,
            'overview': overview,
            'endpoints': endpoints,
            'time_series': time_series,
            'cached_modules': cached_modules
        }
    finally:
        conn.close()


