import sys
import os
import json
import requests
import re

# Add current folder to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── Load environment variables from systemd service ──
service_paths = [
    '/etc/systemd/system/zohomap.service',
    '/lib/systemd/system/zohomap.service'
]
loaded_env = {}
for path in service_paths:
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Find all Environment= lines
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith('Environment='):
                        env_str = line.split('Environment=', 1)[1]
                        if (env_str.startswith('"') and env_str.endswith('"')) or (env_str.startswith("'") and env_str.endswith("'")):
                            env_str = env_str[1:-1]
                        for item in env_str.split():
                            if '=' in item:
                                k, v = item.split('=', 1)
                                os.environ[k] = v
                                loaded_env[k] = v
            print(f"Loaded environment variables: {list(loaded_env.keys())}")
            break
        except Exception as e:
            print(f"Could not read {path}: {e}")

if 'APP_SECRET_KEY' not in os.environ:
    os.environ['APP_SECRET_KEY'] = 'dummy_secret_for_diagnostic_run'

import app
import database
import zoho_api

print("Database URI:", database.DB_URI)
print("Is Postgres:", database.IS_POSTGRES)

# Get admin access token
admin_token = app._get_admin_access_token()
if not admin_token:
    print("Error: No admin token could be generated. Please make sure the admin has logged in.")
    sys.exit(1)

print("\n=== 1. FRANCHISES MODULE LIST ===")
headers = {'Authorization': f'Zoho-oauthtoken {admin_token}'}
# Fetch with basic fields to bypass REQUIRED_PARAM_MISSING
resp = requests.get(
    f'{zoho_api.ZOHO_API_URL}/crm/v3/Franchises',
    headers=headers,
    params={'fields': 'id,Name,Pirtek_Franchise_ID,Franchise_Standard_Users,Franchise_Admin_User', 'per_page': 200},
    timeout=10
)
if resp.ok:
    data = resp.json().get('data', [])
    print(f"Total Franchises found: {len(data)}")
    for f in data[:20]:
        print(f"Name: {f.get('Name')} | ID: {f.get('id')} | Pirtek ID: {f.get('Pirtek_Franchise_ID')}")
        print(f"  Franchise_Standard_Users: {f.get('Franchise_Standard_Users')}")
        print(f"  Franchise_Admin_User: {f.get('Franchise_Admin_User')}")
        print("-" * 40)
else:
    print("Failed to fetch Franchises:", resp.status_code, resp.text)

print("\n=== 2. ALL USERS IN CRM ===")
page = 1
all_crm_users = []
while True:
    r = requests.get(
        f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type=AllUsers&page={page}",
        headers=headers,
        timeout=8
    )
    if not r.ok:
        print(f"Users API page {page} failed: {r.text}")
        break
    users = r.json().get('users', [])
    if not users:
        break
    for u in users:
        all_crm_users.append(u)
        print(f"Name: {u.get('full_name')} | CRM ID: {u['id']} | Email: {u.get('email')} | Status: {u.get('status')} | Profile: {u.get('profile', {}).get('name')}")
    if len(users) < 100:
        break
    page += 1

print(f"\nTotal CRM Users Fetched: {len(all_crm_users)}")
