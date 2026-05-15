import sqlite3
import psycopg2
import psycopg2.extras
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
    pg_conn = psycopg2.connect(rds_uri)
    pg_c = pg_conn.cursor()
except Exception as e:
    print(f"ERROR connecting to PostgreSQL: {e}")
    sys.exit(1)

# 3. Initialize Postgres Schema
print("\nInitializing PostgreSQL Schema...")
import database
database.init_db() # This will use the new DB_URI from config.ini

def migrate_table(table_name, insert_query, transform_fn=None):
    print(f"Migrating {table_name}...")
    try:
        rows = sqlite_c.execute(f"SELECT * FROM {table_name}").fetchall()
        print(f"  Found {len(rows)} rows.")
        
        if not rows:
            return
            
        count = 0
        for row in rows:
            data = dict(row)
            if transform_fn:
                data = transform_fn(data)
                
            pg_c.execute(insert_query, data)
            count += 1
            
        pg_conn.commit()
        print(f"  Successfully migrated {count} rows.")
    except Exception as e:
        print(f"  Skipped/Error migrating {table_name}: {e}")
        pg_conn.rollback()

# Migrate global_settings
migrate_table('global_settings', '''
    INSERT INTO global_settings (key, value)
    VALUES (%(key)s, %(value)s)
    ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
''')

# Migrate geocode_cache
migrate_table('geocode_cache', '''
    INSERT INTO geocode_cache (address, lat, lng)
    VALUES (%(address)s, %(lat)s, %(lng)s)
    ON CONFLICT (address) DO UPDATE SET lat=EXCLUDED.lat, lng=EXCLUDED.lng
''')

# Migrate module_config
migrate_table('module_config', '''
    INSERT INTO module_config (user_id, module_name, location_type, field_mappings, marker_color, marker_icon, is_shared)
    VALUES (%(user_id)s, %(module_name)s, %(location_type)s, %(field_mappings)s, %(marker_color)s, %(marker_icon)s, %(is_shared)s)
    ON CONFLICT (user_id, module_name) DO UPDATE SET 
        location_type=EXCLUDED.location_type,
        field_mappings=EXCLUDED.field_mappings,
        marker_color=EXCLUDED.marker_color,
        marker_icon=EXCLUDED.marker_icon,
        is_shared=EXCLUDED.is_shared
''')

# Migrate module_records
migrate_table('module_records', '''
    INSERT INTO module_records (id, user_id, module_name, name, lat, lng, color, record_data)
    VALUES (%(id)s, %(user_id)s, %(module_name)s, %(name)s, %(lat)s, %(lng)s, %(color)s, %(record_data)s)
    ON CONFLICT (id, module_name, user_id) DO UPDATE SET
        name=EXCLUDED.name,
        lat=EXCLUDED.lat,
        lng=EXCLUDED.lng,
        color=EXCLUDED.color,
        record_data=EXCLUDED.record_data
''')

print("\n=============================================")
print(" Migration Complete!")
print("=============================================")
sqlite_conn.close()
pg_conn.close()
