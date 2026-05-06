import requests
from configparser import ConfigParser
from urllib.parse import urlencode

config = ConfigParser()
config.read('config.ini')

ZOHO_CLIENT_ID = config['ZOHO'].get('client_id')
ZOHO_CLIENT_SECRET = config['ZOHO'].get('client_secret')
ZOHO_REDIRECT_URI = config['ZOHO'].get('redirect_uri')
ZOHO_ACCOUNTS_URL = config['ZOHO'].get('accounts_url', 'https://accounts.zoho.com')
ZOHO_API_URL = config['ZOHO'].get('api_url', 'https://www.zohoapis.com')

def get_authorization_url():
    params = {
        'scope': 'ZohoCRM.modules.all,ZohoCRM.settings.all,ZohoCRM.users.READ',
        'client_id': ZOHO_CLIENT_ID,
        'response_type': 'code',
        'access_type': 'offline',
        'redirect_uri': ZOHO_REDIRECT_URI,
        'prompt': 'consent'
    }
    return f"{ZOHO_ACCOUNTS_URL}/oauth/v2/auth?{urlencode(params)}"

def exchange_code_for_token(code):
    data = {
        'grant_type': 'authorization_code',
        'client_id': ZOHO_CLIENT_ID,
        'client_secret': ZOHO_CLIENT_SECRET,
        'redirect_uri': ZOHO_REDIRECT_URI,
        'code': code
    }
    response = requests.post(f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token", data=data)
    return response.json()

def refresh_access_token(refresh_token):
    data = {
        'grant_type': 'refresh_token',
        'client_id': ZOHO_CLIENT_ID,
        'client_secret': ZOHO_CLIENT_SECRET,
        'refresh_token': refresh_token
    }
    response = requests.post(f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token", data=data)
    return response.json()

def fetch_module_records(module_name, access_token, fields=None, page=1):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    params = {
        'page': page,
        'per_page': 200 # Max per page
    }
    if fields:
        params['fields'] = ','.join(fields)
        
    url = f"{ZOHO_API_URL}/crm/v3/{module_name}"
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 204:
        return {'data': []} # No content
    return response.json()

def fetch_module_metadata(access_token):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    url = f"{ZOHO_API_URL}/crm/v3/settings/modules"
    response = requests.get(url, headers=headers)
    return response.json()

def fetch_module_fields(module_name, access_token):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    url = f"{ZOHO_API_URL}/crm/v3/settings/fields"
    params = {'module': module_name}
    response = requests.get(url, headers=headers, params=params)
    return response.json()

def fetch_org_metadata(access_token):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    # v6 /org is the latest stable for org metadata
    url = f"{ZOHO_API_URL}/crm/v6/org"
    response = requests.get(url, headers=headers)
    return response.json()

def search_records(module_name, criteria, access_token, fields=None):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    url = f"{ZOHO_API_URL}/crm/v3/{module_name}/search"
    params = {'criteria': criteria}
    if fields:
        params['fields'] = ",".join(fields)
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    return {'data': []}

def fetch_user_info(access_token):
    headers = {
        'Authorization': f'Zoho-oauthtoken {access_token}'
    }
    # Fetch current user
    url = f"{ZOHO_API_URL}/crm/v3/users?type=CurrentUser"
    response = requests.get(url, headers=headers)
    return response.json()
