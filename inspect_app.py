import sys
import os
import json
import requests

# Add current folder to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
resp = requests.get(
    f'{zoho_api.ZOHO_API_URL}/crm/v3/Franchises',
    headers=headers,
    params={'per_page': 200},
    timeout=10
)
if resp.ok:
    data = resp.json().get('data', [])
    print(f"Total Franchises found: {len(data)}")
    for f in data[:15]:
        print(f"Name: {f.get('Name')} | ID: {f.get('id')} | Pirtek ID: {f.get('Pirtek_Franchise_ID')}")
        # print any standard/admin user assignments
        print(f"  Franchise_Standard_Users: {f.get('Franchise_Standard_Users')}")
        print(f"  Franchise_Admin_User: {f.get('Franchise_Admin_User')}")
else:
    print("Failed to fetch Franchises:", resp.status_code, resp.text)

print("\n=== 2. USER DETAILS (zohotest3@pirtekusa.com) ===")
# Try to resolve zohotest3@pirtekusa.com email using AllUsers
page = 1
numeric_id = None
while True:
    r = requests.get(
        f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type=AllUsers&page={page}",
        headers=headers,
        timeout=8
    )
    if not r.ok:
        print("Users API failed:", r.text)
        break
    users = r.json().get('users', [])
    if not users:
        break
    for u in users:
        if u.get('email', '').lower() == 'zohotest3@pirtekusa.com':
            numeric_id = u['id']
            print(f"Resolved: {u.get('full_name')} | CRM ID: {u['id']} | Email: {u['email']} | Status: {u.get('status')}")
            break
    if numeric_id or len(users) < 100:
        break
    page += 1

if numeric_id:
    # Get user territories
    r2 = requests.get(
        f"{zoho_api.ZOHO_API_URL}/crm/v3/users/{numeric_id}",
        headers=headers,
        timeout=8
    )
    if r2.ok:
        ud = r2.json().get('users', [{}])[0]
        territories = ud.get('territories', [])
        print("User Territories:", [t.get('name') for t in territories])
    else:
        print("Failed to get territories:", r2.text)
else:
    print("User zohotest3@pirtekusa.com was not found in CRM user pages.")
