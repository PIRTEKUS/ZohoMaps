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
    # Table for Module Configuration
    c.execute('''
        CREATE TABLE IF NOT EXISTS module_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_name TEXT UNIQUE NOT NULL,
            location_type TEXT NOT NULL,  -- 'address' or 'coordinates'
            field_mappings TEXT NOT NULL, -- JSON string of mapped fields
            marker_color TEXT NOT NULL
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

def get_all_module_configs():
    conn = get_db_connection()
    configs = conn.execute('SELECT * FROM module_config').fetchall()
    conn.close()
    
    results = []
    for row in configs:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        results.append(r)
    return results

def get_module_config(module_name):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM module_config WHERE module_name = ?', (module_name,)).fetchone()
    conn.close()
    if row:
        r = dict(row)
        r['field_mappings'] = json.loads(r['field_mappings'])
        return r
    return None

def save_module_config(module_name, location_type, field_mappings, marker_color):
    conn = get_db_connection()
    c = conn.cursor()
    field_mappings_str = json.dumps(field_mappings)
    
    c.execute('''
        INSERT INTO module_config (module_name, location_type, field_mappings, marker_color)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(module_name) DO UPDATE SET
            location_type=excluded.location_type,
            field_mappings=excluded.field_mappings,
            marker_color=excluded.marker_color
    ''', (module_name, location_type, field_mappings_str, marker_color))
    
    conn.commit()
    conn.close()

def delete_module_config(module_name):
    conn = get_db_connection()
    conn.execute('DELETE FROM module_config WHERE module_name = ?', (module_name,))
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
