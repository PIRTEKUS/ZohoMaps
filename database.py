import sqlite3
import json
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')
DB_URI = config['APP']['database_uri'].replace('sqlite:///', '')

def get_db_connection():
    conn = sqlite3.connect(DB_URI, timeout=30.0) # Increase timeout
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # Check current schema version
    c.execute("CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)")
    row = c.execute("SELECT value FROM global_settings WHERE key = 'schema_version'").fetchone()
    schema_version = int(row['value']) if row else 0
    
    # Version 2 is the multi-tenant version
    if schema_version < 2:
        print("Migrating to schema version 2 (Multi-tenancy reset)...")
        # The user requested a clean start to fix constraint issues
        c.execute("DROP TABLE IF EXISTS module_config")
        c.execute("DROP TABLE IF EXISTS module_records")
        c.execute("DROP TABLE IF EXISTS module_config_old")
        c.execute("DROP TABLE IF EXISTS module_records_old")
        
        # Update version
        c.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('schema_version', '2')")

    # Table for Module Configuration (Clean Slate)
    c.execute('''
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
            # Check if column exists first to be safe
            cols = [col[1] for col in c.execute("PRAGMA table_info(module_config)").fetchall()]
            if 'is_shared' not in cols:
                c.execute("ALTER TABLE module_config ADD COLUMN is_shared INTEGER NOT NULL DEFAULT 0")
        except Exception as e:
            print(f"Migration error: {e}")
        c.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('schema_version', '3')")

    # Table for Cached Zoho Records (Clean Slate)
    c.execute('''
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

    # Table for Geocode Caching (Keep this, it's expensive to refill)
    c.execute('''
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lng REAL
        )
    ''')

    # Ensure unique index exists for safety
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_module ON module_config (user_id, module_name)")
    except Exception:
        pass
        
    conn.commit()
    conn.close()

def get_global_setting(key, default=None):
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM global_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    if row:
        return row['value']
    return default

def set_global_setting(key, value):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO global_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    ''', (key, str(value)))
    conn.commit()
    conn.close()

def get_all_module_configs(user_id):
    conn = get_db_connection()
    configs = conn.execute('SELECT * FROM module_config WHERE user_id = ?', (str(user_id),)).fetchall()
    conn.close()
    
    results = []
    for row in configs:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_module_config(user_id, module_name):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM module_config WHERE user_id = ? AND module_name = ?', (str(user_id), module_name)).fetchone()
    conn.close()
    if row:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        return r
    return None

def save_module_config(user_id, module_name, location_type, field_mappings, marker_color, marker_icon='pin', is_shared=False):
    conn = get_db_connection()
    c = conn.cursor()
    field_mappings_str = json.dumps(field_mappings)
    
    c.execute('''
        INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon, is_shared)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, module_name) DO UPDATE SET
            location_type=excluded.location_type,
            field_mappings=excluded.field_mappings,
            marker_color=excluded.marker_color,
            marker_icon=excluded.marker_icon,
            is_shared=excluded.is_shared
    ''', (str(user_id), module_name, location_type, field_mappings_str, marker_color, marker_icon, 1 if is_shared else 0))
    
    conn.commit()
    conn.close()

def get_shared_configs():
    conn = get_db_connection()
    configs = conn.execute('SELECT * FROM module_config WHERE is_shared = 1').fetchall()
    conn.close()
    
    results = []
    for row in configs:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_effective_configs(user_id):
    """
    Returns the effective module configs for a user:
    - If they have their own configs, return those.
    - Always merge in any shared configs they don't already have.
    This lets team users automatically see shared configurations.
    """
    conn = get_db_connection()
    own = conn.execute(
        'SELECT * FROM module_config WHERE user_id = ?', (str(user_id),)
    ).fetchall()
    own_modules = {r['module_name'] for r in own}
    
    shared = conn.execute(
        'SELECT * FROM module_config WHERE is_shared = 1 AND user_id != ?', (str(user_id),)
    ).fetchall()
    conn.close()
    
    results = []
    for row in list(own) + [r for r in shared if r['module_name'] not in own_modules]:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def delete_module_config(user_id, module_name):
    conn = get_db_connection()
    conn.execute('DELETE FROM module_config WHERE user_id = ? AND module_name = ?', (str(user_id), module_name))
    conn.commit()
    conn.close()

def get_cached_geocode(address):
    conn = get_db_connection()
    row = conn.execute('SELECT lat, lng FROM geocode_cache WHERE address = ?', (address,)).fetchone()
    conn.close()
    if row:
        return {'lat': row['lat'], 'lng': row['lng']}
    return None

def set_cached_geocode(address, lat, lng):
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO geocode_cache (address, lat, lng)
        VALUES (?, ?, ?)
    ''', (address, lat, lng))
    conn.commit()
    conn.close()

def save_module_record(user_id, id, module_name, name, lat, lng, color, record_data):
    save_module_records_batch(user_id, [(id, module_name, name, lat, lng, color, record_data)])

def save_module_records_batch(user_id, records):
    """Save multiple records in a single transaction."""
    conn = get_db_connection()
    try:
        conn.execute('BEGIN TRANSACTION')
        for rec in records:
            id, module_name, name, lat, lng, color, record_data = rec
            conn.execute('''
                INSERT INTO module_records (user_id, id, module_name, name, lat, lng, color, record_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, module_name, user_id) DO UPDATE SET
                    name=excluded.name,
                    lat=excluded.lat,
                    lng=excluded.lng,
                    color=excluded.color,
                    record_data=excluded.record_data
            ''', (str(user_id), str(id), module_name, name, lat, lng, color, json.dumps(record_data)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_records_in_bounds(user_id, min_lat, max_lat, min_lng, max_lng):
    """
    Returns map records for exactly ONE user_id within the given lat/lng bounds.

    ╔══════════════════════════════════════════════════════════════════════╗
    ║  DATA PRIVACY — DO NOT MODIFY WITHOUT A FULL SECURITY REVIEW        ║
    ║                                                                      ║
    ║  Records in module_records are stored per-user. Mixing user_ids     ║
    ║  here would expose one user's CRM data to another user.             ║
    ║                                                                      ║
    ║  The query MUST remain `WHERE user_id = ?` (single user only).      ║
    ║  Shared configs (is_shared=1) control DISPLAY CONFIGURATION only    ║
    ║  (which modules/fields/colors to show) — NOT data access rights.    ║
    ║                                                                      ║
    ║  Data access is enforced at two levels:                             ║
    ║    1. Zoho CRM API — only returns records the token owner can see.  ║
    ║    2. This query   — only reads records stored for that user_id.    ║
    ╚══════════════════════════════════════════════════════════════════════╝
    """
    conn = get_db_connection()
    if min_lng > max_lng:
        query = '''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND (lng >= ? OR lng <= ?)
            LIMIT 5000
        '''
        rows = conn.execute(query, (str(user_id), min_lat, max_lat, min_lng, max_lng)).fetchall()
    else:
        query = '''
            SELECT * FROM module_records
            WHERE user_id = ? AND lat >= ? AND lat <= ?
            AND lng >= ? AND lng <= ?
            LIMIT 5000
        '''
        rows = conn.execute(query, (str(user_id), min_lat, max_lat, min_lng, max_lng)).fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r['record_data'] = json.loads(r['record_data'])
        results.append(r)
    return results


def clear_module_records(user_id, module_name):
    conn = get_db_connection()
    conn.execute('DELETE FROM module_records WHERE user_id = ? AND module_name = ?', (str(user_id), module_name))
    conn.commit()
    conn.close()
