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

print("\n=== 1. CHECK UNCONFIRMED AND INACTIVE USERS ===")
for utype in ['UnconfirmedUsers', 'InactiveUsers']:
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
            if 'zohotest3' in u.get('email', '').lower() or 'colo' in u.get('full_name', '').lower():
                print(f"  MATCH: Name: {u.get('full_name')} | ID: {u['id']} | Email: {u.get('email')} | Status: {u.get('status')}")
    else:
        print(f"  Failed: {r.text}")

print("\n=== 2. TEST COQL ON LEADS WITH TERRITORY FILTER ===")
# Try COQL query filtering by Territory
queries = [
    "SELECT id, Select_Your_Franchise1 FROM Leads WHERE Territory = 'Colorado Springs' LIMIT 5",
    "SELECT id, Select_Your_Franchise1 FROM Leads WHERE Territories = 'Colorado Springs' LIMIT 5"
]
for q in queries:
    print(f"Running COQL: {q}")
    res = zoho_api.coql_query(q, admin_token)
    recs = res.get('data', [])
    print(f"Result count: {len(recs)}")
    if recs:
        for r in recs[:3]:
            print(f"  Record: {r}")

print("\n=== 3. FETCH TERRITORIES VIA API ===")
# Let's see if we can list territories using the Zoho CRM Territories API
t_url = f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories"
r = requests.get(t_url, headers=headers, timeout=8)
if r.ok:
    t_data = r.json().get('territories', [])
    print(f"Total territories found: {len(t_data)}")
    for t in t_data:
        print(f"Territory: {t.get('name')} | ID: {t.get('id')} | Parent: {t.get('parent_territory', {}).get('name')}")
else:
    print("Failed to fetch territories:", r.status_code, r.text)
