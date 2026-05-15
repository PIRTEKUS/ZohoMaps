import sqlite3
import json
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')
DB_URI = config['APP']['database_uri']

IS_POSTGRES = DB_URI.startswith('postgres')
if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

def get_db_connection():
    if IS_POSTGRES:
        conn = psycopg2.connect(DB_URI)
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
        c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        c = conn.cursor()
        
    c.execute(query, params)
    
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

    # Table for Geocode Caching (Keep this, it's expensive to refill)
    exec_query(conn, '''
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lng REAL
        )
    ''')

    # Ensure unique index exists for safety
    try:
        exec_query(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_module ON module_config (user_id, module_name)")
    except Exception:
        pass
        
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

def get_effective_configs(user_id):
    conn = get_db_connection()
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

def get_cached_geocode(address):
    conn = get_db_connection()
    row = exec_query(conn, 'SELECT lat, lng FROM geocode_cache WHERE address = ?', (address,), fetchone=True)
    conn.close()
    if row:
        return {'lat': row['lat'], 'lng': row['lng']}
    return None

def set_cached_geocode(address, lat, lng):
    conn = get_db_connection()
    exec_query(conn, '''
        INSERT OR REPLACE INTO geocode_cache (address, lat, lng)
        VALUES (?, ?, ?)
    ''', (address, lat, lng))
    conn.commit()
    conn.close()

def save_module_record(user_id, id, module_name, name, lat, lng, color, record_data):
    save_module_records_batch(user_id, [(id, module_name, name, lat, lng, color, record_data)])

def save_module_records_batch(user_id, records):
    conn = get_db_connection()
    try:
        exec_query(conn, 'BEGIN TRANSACTION')
        for rec in records:
            id, module_name, name, lat, lng, color, record_data = rec
            exec_query(conn, '''
                INSERT INTO module_records (user_id, id, module_name, name, lat, lng, color, record_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, module_name, user_id) DO UPDATE SET
                    name=EXCLUDED.name,
                    lat=EXCLUDED.lat,
                    lng=EXCLUDED.lng,
                    color=EXCLUDED.color,
                    record_data=EXCLUDED.record_data
            ''', (str(user_id), str(id), module_name, name, lat, lng, color, json.dumps(record_data)))
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
