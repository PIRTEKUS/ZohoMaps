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

print("\n=== 1. TRIGGER MAPPINGS REBUILD ===")
mappings = app._refresh_user_mappings(admin_token)
if mappings:
    print(f"Successfully rebuilt mapping. Total cached users: {len(mappings)}")
else:
    print("Failed to rebuild mappings cache.")

print("\n=== 2. TEST FRANCHISE RESOLUTIONS ===")
test_users = [
    'zohotest3@pirtekusa.com', # Team User - Colorado Springs
    'zohotest4@pirtekusa.com', # Franchise Owner - Colorado Springs
    'elmwood@sqible.com.au',   # Regular user - Elmwood
    'frapa@pirtekusa.com',      # Admin
    'nonexistent@pirtekusa.com' # Non-existent
]

for email in test_users:
    print(f"\nResolving for: {email}")
    res = app._get_user_franchise_ids(email, admin_token, force_refresh=True)
    print("  Names:", res.get('names'))
    print("  IDs:", res.get('ids'))
    print("  Debug Log:")
    for line in res.get('debug', []):
        print(f"    - {line}")
