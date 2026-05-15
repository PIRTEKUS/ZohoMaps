import sqlite3
import pg8000.dbapi
from urllib.parse import urlparse
from configparser import ConfigParser
import json
import sys

print("=============================================")
print(" ZohoMap SQLite to PostgreSQL Migration Tool")
print("=============================================")

# 1. Load config
config = ConfigParser()
config.read('config.ini')

rds_uri = config['APP'].get('database_uri', '')

if not rds_uri.startswith('postgres'):
    print("ERROR: config.ini [APP] database_uri is not a PostgreSQL URI.")
    print("Please update it to your RDS endpoint (e.g., postgresql://user:pass@host/db)")
    sys.exit(1)

# 2. Connect to both DBs
print("\nConnecting to local SQLite (database.db)...")
sqlite_conn = sqlite3.connect('database.db')
sqlite_conn.row_factory = sqlite3.Row
sqlite_c = sqlite_conn.cursor()

print(f"Connecting to RDS PostgreSQL ({rds_uri.split('@')[-1]})...")
try:
    parsed = urlparse(rds_uri)
    pg_conn = pg8000.dbapi.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip('/')
    )
    pg_conn.autocommit = True
    pg_c = pg_conn.cursor()
except Exception as e:
    print(f"ERROR connecting to PostgreSQL: {e}")
    sys.exit(1)

# 3. Initialize Postgres Schema
print("\nInitializing PostgreSQL Schema...")
import database
database.init_db() # This will use the new DB_URI from config.ini

def migrate_table(table_name, insert_query, transform_fn):
    print(f"Migrating {table_name}...")
    try:
        rows = sqlite_c.execute(f"SELECT * FROM {table_name}").fetchall()
        print(f"  Found {len(rows)} rows.")
        
        if not rows:
            return
            
        count = 0
        for row in rows:
            data = dict(row)
            values = transform_fn(data)
                
            pg_c.execute(insert_query, values)
            count += 1
            
        print(f"  Successfully migrated {count} rows.")
    except Exception as e:
        print(f"  Skipped/Error migrating {table_name}: {e}")

# Migrate global_settings
migrate_table('global_settings', '''
    INSERT INTO global_settings (key, value)
    VALUES (%s, %s)
    ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
''', lambda d: (d['key'], d['value']))

# Migrate geocode_cache
migrate_table('geocode_cache', '''
    INSERT INTO geocode_cache (address, lat, lng)
    VALUES (%s, %s, %s)
    ON CONFLICT (address) DO UPDATE SET lat=EXCLUDED.lat, lng=EXCLUDED.lng
''', lambda d: (d['address'], d['lat'], d['lng']))

# Migrate module_config
migrate_table('module_config', '''
    INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon, is_shared)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (user_id, module_name) DO UPDATE SET 
        location_type=EXCLUDED.location_type,
        field_mappings=EXCLUDED.field_mappings,
        marker_color=EXCLUDED.marker_color,
        marker_icon=EXCLUDED.marker_icon,
        is_shared=EXCLUDED.is_shared
''', lambda d: (d['user_id'], d['module_name'], d['location_type'], d['field_mappings'], d['marker_color'], d['marker_icon'], d['is_shared']))

# Migrate module_records
migrate_table('module_records', '''
    INSERT INTO module_records (id, user_id, module_name, name, lat, lng, color, record_data)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id, module_name, user_id) DO UPDATE SET
        name=EXCLUDED.name,
        lat=EXCLUDED.lat,
        lng=EXCLUDED.lng,
        color=EXCLUDED.color,
        record_data=EXCLUDED.record_data
''', lambda d: (d['id'], d['user_id'], d['module_name'], d['name'], d['lat'], d['lng'], d['color'], d['record_data']))

print("\n=============================================")
print(" Migration Complete!")
print("=============================================")
sqlite_conn.close()
pg_conn.close()
