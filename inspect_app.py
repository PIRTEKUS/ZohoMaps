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

print("\n=== 1. LIST ALL DEACTIVE AND NOTCONFIRMED USERS ===")
for utype in ['DeactiveUsers', 'NotConfirmedUsers']:
    print(f"\nListing users of type: {utype}")
    r = requests.get(
        f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type={utype}",
        headers=headers,
        timeout=8
    )
    if r.ok:
        users = r.json().get('users', [])
        for u in users:
            print(f"  Name: {u.get('full_name')} | ID: {u['id']} | Email: {u.get('email')} | Status: {u.get('status')}")
    else:
        print(f"  Failed: {r.status_code} - {r.text}")

print("\n=== 2. TEST USERS IN TERRITORY ENDPOINT ===")
# Let's test if there is a sub-resource endpoint for users in a territory
t_id = '6959138000001451016'
urls_to_test = [
    f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories/{t_id}/users",
    f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories/{t_id}/associated_users"
]
for url in urls_to_test:
    print(f"Testing URL: {url}")
    r = requests.get(url, headers=headers, timeout=8)
    print(f"  Status: {r.status_code}")
    if r.ok:
        print("  Response keys:", list(r.json().keys()))
        print("  Response preview:", r.json())
    else:
        print("  Error:", r.text[:300])
