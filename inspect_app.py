import sys
import os
import json
import requests

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

admin_token = app._get_admin_access_token()
if not admin_token:
    print("Error: No admin token could be generated.")
    sys.exit(1)

headers = {'Authorization': f'Zoho-oauthtoken {admin_token}'}

print("\n=== 1. FETCH OTHER CRM USER TYPES ===")
# Try other valid Zoho CRM v3 user type values to find zohotest3@pirtekusa.com
user_types = [
    'DeactiveUsers',
    'ConfirmedUsers',
    'NotConfirmedUsers',
    'ActiveUnconfirmedUsers'
]
for utype in user_types:
    print(f"\nFetching users of type: {utype}")
    r = requests.get(
        f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type={utype}",
        headers=headers,
        timeout=8
    )
    if r.ok:
        users = r.json().get('users', [])
        print(f"Count: {len(users)}")
        for u in users:
            email = (u.get('email') or '').lower()
            full_name = (u.get('full_name') or '').lower()
            last_name = (u.get('last_name') or '').lower()
            if 'zohotest3' in email or 'colo' in full_name or 'msst' in last_name:
                print(f"  MATCH: Name: {u.get('full_name')} | ID: {u['id']} | Email: {u.get('email')} | Status: {u.get('status')} | Profile: {u.get('profile', {}).get('name')}")
    else:
        print(f"  Failed: {r.status_code} - {r.text}")

print("\n=== 2. FETCH TERRITORY DETAILS ===")
# Fetch specific territory details for Colorado Springs
t_id = '6959138000001451016'
t_url = f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories/{t_id}"
r = requests.get(t_url, headers=headers, timeout=8)
if r.ok:
    data = r.json().get('territories', [{}])[0]
    print(f"Territory Name: {data.get('name')}")
    # print keys to see if users are listed
    print("Keys in territory details:", list(data.keys()))
    # print any likely user list fields
    for k in ['users', 'assigned_users', 'manager', 'reporting_to']:
        if k in data:
            print(f"Field '{k}':", data[k])
else:
    print(f"Failed to fetch territory details: {r.status_code} - {r.text}")
