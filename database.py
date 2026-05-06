import sqlite3
import json
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')
DB_URI = config['APP']['database_uri'].replace('sqlite:///', '')

def get_db_connection():
    conn = sqlite3.connect(DB_URI)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Table for Module Configuration (partitioned by user_id)
    # We recreate it to ensure the UNIQUE constraint is correct (user_id, module_name)
    # instead of just (module_name) which might exist from older versions
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='module_config'")
    if c.fetchone():
        # Check if we need to migrate (if the old unique constraint on module_name exists)
        c.execute("PRAGMA index_list('module_config')")
        indices = c.fetchall()
        has_user_id_unique = any('idx_user_module' in idx['name'] for idx in indices)
        
        if not has_user_id_unique:
            # Recreate table strategy
            c.execute("ALTER TABLE module_config RENAME TO module_config_old")
            c.execute('''
                CREATE TABLE module_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    location_type TEXT NOT NULL,
                    field_mappings TEXT NOT NULL,
                    marker_color TEXT NOT NULL,
                    marker_icon TEXT NOT NULL DEFAULT 'pin',
                    UNIQUE(user_id, module_name)
                )
            ''')
            # Try to copy data back, setting user_id to 'legacy' for old records
            try:
                c.execute('''
                    INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon)
                    SELECT 'legacy', module_name, location_type, field_mappings, marker_color, marker_icon FROM module_config_old
                ''')
            except Exception:
                pass
            c.execute("DROP TABLE module_config_old")
    else:
        c.execute('''
            CREATE TABLE module_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                module_name TEXT NOT NULL,
                location_type TEXT NOT NULL,
                field_mappings TEXT NOT NULL,
                marker_color TEXT NOT NULL,
                marker_icon TEXT NOT NULL DEFAULT 'pin',
                UNIQUE(user_id, module_name)
            )
        ''')

    # Table for Cached Zoho Records
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='module_records'")
    if c.fetchone():
        # Check columns
        c.execute("PRAGMA table_info('module_records')")
        cols = [col['name'] for col in c.fetchall()]
        if 'user_id' not in cols:
            c.execute("ALTER TABLE module_records RENAME TO module_records_old")
            c.execute('''
                CREATE TABLE module_records (
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
            try:
                c.execute('''
                    INSERT INTO module_records (id, user_id, module_name, name, lat, lng, color, record_data)
                    SELECT id, 'legacy', module_name, name, lat, lng, color, record_data FROM module_records_old
                ''')
            except Exception:
                pass
            c.execute("DROP TABLE module_records_old")
    else:
        c.execute('''
            CREATE TABLE module_records (
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

    # Table for Geocode Caching
    c.execute('''
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lng REAL
        )
    ''')
    # Table for Global Settings
    c.execute('''
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT
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

def save_module_config(user_id, module_name, location_type, field_mappings, marker_color, marker_icon='pin'):
    conn = get_db_connection()
    c = conn.cursor()
    field_mappings_str = json.dumps(field_mappings)
    
    c.execute('''
        INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, module_name) DO UPDATE SET
            location_type=excluded.location_type,
            field_mappings=excluded.field_mappings,
            marker_color=excluded.marker_color,
            marker_icon=excluded.marker_icon
    ''', (str(user_id), module_name, location_type, field_mappings_str, marker_color, marker_icon))
    
    conn.commit()
    conn.close()

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
    conn = get_db_connection()
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
    conn.close()

def get_records_in_bounds(user_id, min_lat, max_lat, min_lng, max_lng):
    conn = get_db_connection()
    if min_lng > max_lng:
        query = '''
            SELECT * FROM module_records 
            WHERE user_id = ? AND lat >= ? AND lat <= ? 
            AND (lng >= ? OR lng <= ?)
        '''
        rows = conn.execute(query, (str(user_id), min_lat, max_lat, min_lng, max_lng)).fetchall()
    else:
        query = '''
            SELECT * FROM module_records 
            WHERE user_id = ? AND lat >= ? AND lat <= ? 
            AND lng >= ? AND lng <= ?
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
