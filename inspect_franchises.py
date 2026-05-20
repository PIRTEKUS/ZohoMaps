import requests
import sqlite3
import sys
sys.path.append('.')
import app
import zoho_api

admin_token = app._get_admin_access_token()
if not admin_token:
    print("No admin token")
    sys.exit(1)

headers = {'Authorization': f'Zoho-oauthtoken {admin_token}'}
resp = requests.get(
    f'{zoho_api.ZOHO_API_URL}/crm/v3/Franchises',
    headers=headers,
    params={'per_page': 200},
    timeout=10
)
if resp.ok:
    data = resp.json()
    records = data.get('data', [])
    print(f"Fetched {len(records)} franchises:")
    for r in records[:15]:
        print(f"Name: {r.get('Name')} | ID: {r.get('id')} | Pirtek ID: {r.get('Pirtek_Franchise_ID')}")
        # Print all keys to see field structure
        print("Keys:", list(r.keys()))
        print("-" * 40)
else:
    print("Failed:", resp.status_code, resp.text)
