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

print("\n=== 1. FETCH ALL TERRITORIES ===")
t_url = f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories"
r = requests.get(t_url, headers=headers, timeout=8)
if not r.ok:
    print("Failed to fetch territories:", r.text)
    sys.exit(1)

territories = r.json().get('territories', [])
print(f"Found {len(territories)} territories.")

print("\n=== 2. BUILD USER LOOKUP FROM TERRITORIES ===")
email_lookup = {}
for t in territories:
    t_name = t.get('name')
    t_id = t.get('id')
    print(f"Querying users for territory: {t_name} ({t_id})...")
    u_url = f"{zoho_api.ZOHO_API_URL}/crm/v3/settings/territories/{t_id}/users"
    u_resp = requests.get(u_url, headers=headers, timeout=8)
    if u_resp.ok:
        t_users = u_resp.json().get('users', [])
        for u in t_users:
            email = (u.get('email') or '').lower()
            if email:
                if email not in email_lookup:
                    email_lookup[email] = {
                        'id': u.get('id'),
                        'full_name': u.get('full_name'),
                        'email': u.get('email'),
                        'status': u.get('status'),
                        'category': u.get('category'),
                        'franchise_field_value': u.get('Franchise'),
                        'territories': []
                    }
                email_lookup[email]['territories'].append(t_name)
    else:
        print(f"  Failed for {t_name}: {u_resp.status_code}")

print("\n=== 3. CONSOLIDATED USER MAP FROM TERRITORIES ===")
print(json.dumps(email_lookup, indent=2))
