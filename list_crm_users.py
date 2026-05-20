import requests
import json
import sqlite3

# Fetch the admin refresh token from db
conn = sqlite3.connect('database.db')
conn.row_factory = sqlite3.Row
row = conn.execute("SELECT value FROM global_settings WHERE key = 'admin_refresh_token'").fetchone()
refresh_token = row[0] if row else None
print("Refresh token found:", bool(refresh_token))

# Let's get access token
if refresh_token:
    config = {}
    # Let's import zoho_api
    import sys
    sys.path.append('.')
    import zoho_api
    # We can get access token via zoho_api client
    # Or just exchange it manually
    import app
    admin_token = app._get_admin_access_token()
    print("Admin token obtained:", bool(admin_token))
    
    if admin_token:
        # Get users
        r = requests.get(
            f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type=AllUsers",
            headers={'Authorization': f'Zoho-oauthtoken {admin_token}'},
            timeout=8
        )
        print("Status:", r.status_code)
        if r.ok:
            users_data = r.json()
            for u in users_data.get('users', []):
                print(f"User: {u.get('full_name')} | ID: {u.get('id')} | Email: {u.get('email')} | Status: {u.get('status')}")
        else:
            print("Response:", r.text)
