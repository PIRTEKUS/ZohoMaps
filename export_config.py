#!/usr/bin/env python3
"""
ZohoMap Config Export / Import Tool
====================================
Exports module_config and global_settings (i.e. your map module mappings)
from one ZohoMap database and imports them into another.

Skips large/transient data (module_records, geocode_cache) that will be
rebuilt automatically by the app via a Sync.

Usage
-----
  # On the SOURCE server (dev / old server) — creates mappings_export.json:
  python3 export_config.py --export mappings_export.json

  # On the TARGET server (AWS / new server) — loads mappings_export.json:
  python3 export_config.py --import mappings_export.json

The script reads DATABASE_URI from the environment variable (systemd) or
from config.ini [APP] database_uri, exactly as the main app does.
"""

import argparse
import json
import os
import sys
from configparser import ConfigParser
from datetime import datetime, timezone

# ── Resolve database URI (same logic as database.py) ─────────────────────────
_cfg = ConfigParser()
_cfg.read('config.ini')
_app_cfg = _cfg['APP'] if _cfg.has_section('APP') else {}
DB_URI = os.environ.get('DATABASE_URI') or _app_cfg.get('database_uri', 'sqlite:///database.db')

IS_POSTGRES = DB_URI.startswith('postgres')

def get_connection():
    if IS_POSTGRES:
        import pg8000.dbapi
        from urllib.parse import urlparse
        p = urlparse(DB_URI)
        conn = pg8000.dbapi.connect(
            user=p.username, password=p.password,
            host=p.hostname, port=p.port or 5432,
            database=p.path.lstrip('/')
        )
        conn.autocommit = True
        return conn, 'postgres'
    else:
        import sqlite3
        path = DB_URI.replace('sqlite:///', '')
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn, 'sqlite'


def do_export(output_file):
    print(f"Connecting to: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
    conn, db_type = get_connection()
    c = conn.cursor()

    def fetchall(query):
        c.execute(query)
        if IS_POSTGRES:
            cols = [d[0] for d in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        else:
            return [dict(row) for row in c.fetchall()]

    # ── Skip keys that are user-session-specific or contain encrypted tokens ──
    SKIP_KEYS = {
        'admin_refresh_token',  # encrypted — won't decrypt on new server
        'schema_version',       # managed by init_db()
    }
    # Also skip per-user franchise caches (franchise_ids_<user_id>)
    all_settings = fetchall("SELECT * FROM global_settings")
    settings = [
        s for s in all_settings
        if s['key'] not in SKIP_KEYS and not s['key'].startswith('franchise_ids_')
    ]

    configs = fetchall("SELECT * FROM module_config")

    conn.close()

    payload = {
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'source_db': 'postgresql' if IS_POSTGRES else 'sqlite',
        'module_config': configs,
        'global_settings': settings,
    }

    with open(output_file, 'w') as f:
        json.dump(payload, f, indent=2)

    print(f"\n✅ Exported:")
    print(f"   {len(configs)} module config(s)  →  {output_file}")
    print(f"   {len(settings)} global setting(s) →  {output_file}")
    print(f"\nCopy {output_file} to the target server, then run:")
    print(f"   python3 export_config.py --import {output_file}")


def do_import(input_file):
    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}")
        sys.exit(1)

    with open(input_file) as f:
        payload = json.load(f)

    configs  = payload.get('module_config', [])
    settings = payload.get('global_settings', [])

    print(f"Import file exported at: {payload.get('exported_at', 'unknown')}")
    print(f"Connecting to: {'PostgreSQL' if IS_POSTGRES else 'SQLite'}")
    conn, db_type = get_connection()
    c = conn.cursor()

    def upsert(query_pg, query_sqlite, params):
        q = query_pg if IS_POSTGRES else query_sqlite
        c.execute(q, params)

    # ── global_settings ───────────────────────────────────────────────────────
    ok_settings = 0
    for s in settings:
        try:
            upsert(
                "INSERT INTO global_settings (key,value) VALUES (%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                "INSERT OR REPLACE INTO global_settings (key,value) VALUES (?,?)",
                (s['key'], s['value'])
            )
            ok_settings += 1
        except Exception as e:
            print(f"  ⚠️  Skipped setting '{s['key']}': {e}")

    # ── module_config ─────────────────────────────────────────────────────────
    ok_configs = 0
    for cfg in configs:
        try:
            upsert(
                """INSERT INTO module_config
                       (user_id,module_name,location_type,field_mappings,marker_color,marker_icon,is_shared)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(user_id,module_name) DO UPDATE SET
                       location_type=EXCLUDED.location_type,
                       field_mappings=EXCLUDED.field_mappings,
                       marker_color=EXCLUDED.marker_color,
                       marker_icon=EXCLUDED.marker_icon,
                       is_shared=EXCLUDED.is_shared""",
                """INSERT OR REPLACE INTO module_config
                       (user_id,module_name,location_type,field_mappings,marker_color,marker_icon,is_shared)
                   VALUES (?,?,?,?,?,?,?)""",
                (cfg['user_id'], cfg['module_name'], cfg['location_type'],
                 cfg['field_mappings'], cfg['marker_color'], cfg.get('marker_icon','pin'),
                 cfg.get('is_shared', 0))
            )
            ok_configs += 1
        except Exception as e:
            print(f"  ⚠️  Skipped config '{cfg.get('module_name','?')}': {e}")

    if not IS_POSTGRES:
        conn.commit()
    conn.close()

    print(f"\n✅ Imported:")
    print(f"   {ok_configs}/{len(configs)} module config(s)")
    print(f"   {ok_settings}/{len(settings)} global setting(s)")
    print(f"\nRestart the app and run a Sync to rebuild the map data.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ZohoMap config export/import tool')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', metavar='FILE', help='Export configs to JSON file')
    group.add_argument('--import', metavar='FILE', dest='import_file', help='Import configs from JSON file')
    args = parser.parse_args()

    if args.export:
        do_export(args.export)
    else:
        do_import(args.import_file)
