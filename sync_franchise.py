#!/usr/bin/env python3
"""
ZohoMap Manual Franchise Sync Tool
===================================
Run sync for a specific module and franchise.

Usage Examples:
  # Using Franchise ID for one module:
  python sync_franchise.py --module Leads --franchise 6959138000038410001

  # Using Franchise Name for one module:
  python sync_franchise.py --module Accounts --franchise "Orlando East"

  # Sync all modules for a franchise:
  python sync_franchise.py --franchise "Orlando East"
"""

import sys
import os
import json
import argparse

# Load env variables if available (e.g. /etc/zohomap/app.env)
_ENV_FILE = '/etc/zohomap/app.env'
if os.path.exists(_ENV_FILE):
    try:
        with open(_ENV_FILE) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _, _v = _line.partition('=')
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

# Ensure working directory is application root
app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(app_dir)
sys.path.insert(0, app_dir)

from app import app, _get_admin_access_token, build_fields_list, process_and_save_record
import database
import zoho_api

FRANCHISE_FIELD_MAP = {
    'Accounts':          'Franchise',
    'Leads':             'Select_Your_Franchise1',
    'Ship_To_Addresses': 'Franchise'
}

def sync_franchise_module(module_name, franchise_id_or_name):
    with app.app_context():
        admin_token = _get_admin_access_token()
        if not admin_token:
            print("[ERROR] Could not get admin access token. Ensure admin is logged in or refresh token is available.")
            sys.exit(1)

        # Resolve Franchise ID if a name was passed
        franchise_id = str(franchise_id_or_name).strip()
        franchise_display_name = franchise_id

        cached_franchises_str = database.get_global_setting('cached_all_franchises', '[]')
        try:
            cached_list = json.loads(cached_franchises_str)
            for f in cached_list:
                fid = str(f.get('id', ''))
                fname = str(f.get('name', ''))
                if franchise_id.lower() == fname.lower() or franchise_id == fid:
                    franchise_id = fid
                    franchise_display_name = fname
                    break
        except Exception as e:
            print(f"[WARN] Error reading cached franchises: {e}")

        print(f"\n==========================================")
        print(f" Syncing Module  : {module_name}")
        print(f" Franchise Target : {franchise_display_name} (ID: {franchise_id})")
        print(f"==========================================\n")

        # Get module config
        effective_configs = database.get_effective_configs(user_id=None, is_admin=True)
        config = next((c for c in effective_configs if c['module_name'] == module_name), None)
        if not config:
            print(f"[ERROR] Module '{module_name}' is not configured in Module Settings.")
            sys.exit(1)

        franchise_field = FRANCHISE_FIELD_MAP.get(module_name, 'Franchise')
        criteria = f"({franchise_field}.id:in:{franchise_id})"
        print(f"Using search criteria: {criteria}")

        # Fetch records using admin token & criteria
        field_metadata = zoho_api.fetch_module_fields(module_name, admin_token)
        sync_fields_list = build_fields_list(module_name, config, field_metadata)

        page = 1
        page_token = None
        more_records = True
        total_synced = 0
        total_geocoded = 0

        while more_records:
            print(f"Fetching page {page} for {module_name}...")
            data = zoho_api.search_records(module_name, criteria, admin_token, fields=sync_fields_list, page=page, page_token=page_token)
            
            records = data.get('data', [])
            info = data.get('info', {})
            more_records = info.get('more_records', False)
            page_token = info.get('next_page_token')

            if not records:
                print(f"No records found for page {page}.")
                break

            print(f"Processing {len(records)} records from page {page}...")
            for record in records:
                result = process_and_save_record(
                    user_id=None,
                    module_name=module_name,
                    record=record,
                    config=config,
                    is_admin=True
                )
                if result == 'synced':
                    total_synced += 1
                elif result == 'geocoded':
                    total_synced += 1
                    total_geocoded += 1

            page += 1

        print(f"\n==========================================")
        print(f" SUCCESS: Synced {total_synced} records for {module_name} ({franchise_display_name}).")
        if total_geocoded > 0:
            print(f" (Geocoded {total_geocoded} new addresses)")
        print(f"==========================================\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Sync a single module for a single franchise in ZohoMap.")
    parser.add_argument('--module', '-m', help="Module name (e.g. Leads, Accounts, Ship_To_Addresses)")
    parser.add_argument('--franchise', '-f', required=True, help="Franchise ID or Franchise Name (e.g. 6959138000038410001 or 'Orlando East')")
    
    args = parser.parse_args()
    
    modules = [args.module] if args.module else ['Accounts', 'Leads', 'Ship_To_Addresses']
    for mod in modules:
        sync_franchise_module(mod, args.franchise)
