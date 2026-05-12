import requests
from configparser import ConfigParser
from urllib.parse import urlencode

config = ConfigParser()
config.read('config.ini')

ZOHO_CLIENT_ID = config['ZOHO'].get('client_id')
ZOHO_CLIENT_SECRET = config['ZOHO'].get('client_secret')

# Support comma-separated list of redirect URIs (e.g. IP + DNS)
_raw_redirect_uris = config['ZOHO'].get('redirect_uri', '')
ZOHO_REDIRECT_URIS = [u.strip() for u in _raw_redirect_uris.split(',') if u.strip()]
ZOHO_REDIRECT_URI = ZOHO_REDIRECT_URIS[0] if ZOHO_REDIRECT_URIS else ''

ZOHO_ACCOUNTS_URL = config['ZOHO'].get('accounts_url', 'https://accounts.zoho.com')
ZOHO_API_URL = config['ZOHO'].get('api_url', 'https://www.zohoapis.com')

def get_matching_redirect_uri(request_host_url: str) -> str:
    """Return the configured redirect URI whose base URL best matches the incoming request host.
    Falls back to the first URI if no match found."""
    # Normalise — strip trailing slash
    host = request_host_url.rstrip('/')
    for uri in ZOHO_REDIRECT_URIS:
        # Compare scheme+host portion only (ignore path)
        from urllib.parse import urlparse
        parsed_uri = urlparse(uri)
        uri_base = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
        if host.startswith(uri_base) or uri_base.startswith(host):
            return uri
    # Fallback: return first URI
    return ZOHO_REDIRECT_URI

def get_authorization_url(redirect_uri: str = None):
    uri = redirect_uri or ZOHO_REDIRECT_URI
    params = {
        # AaaServer.profile.Read allows /oauth/user/info fallback for team users
        'scope': 'ZohoCRM.modules.all,ZohoCRM.settings.all,ZohoCRM.users.READ,AaaServer.profile.Read',
        'client_id': ZOHO_CLIENT_ID,
        'response_type': 'code',
        'access_type': 'offline',
        'redirect_uri': uri,
        'prompt': 'consent'
    }
    return f"{ZOHO_ACCOUNTS_URL}/oauth/v2/auth?{urlencode(params)}"

def exchange_code_for_token(code, redirect_uri: str = None):
    uri = redirect_uri or ZOHO_REDIRECT_URI
    data = {
        'grant_type': 'authorization_code',
        'client_id': ZOHO_CLIENT_ID,
        'client_secret': ZOHO_CLIENT_SECRET,
        'redirect_uri': uri,
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
    headers = {'Authorization': f'Zoho-oauthtoken {access_token}'}
    url = f"{ZOHO_API_URL}/crm/v6/org"
    response = requests.get(url, headers=headers, timeout=8)
    return response.json()

def fetch_org_metadata_v3(access_token):
    """Fallback: try the v3 org endpoint if v6 fails."""
    headers = {'Authorization': f'Zoho-oauthtoken {access_token}'}
    url = f"{ZOHO_API_URL}/crm/v3/org"
    response = requests.get(url, headers=headers, timeout=8)
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
    """
    Fetch current user info.
    Primary: CRM /users API (admins + orgs that grant ZohoCRM.users.READ).
    Fallback: Zoho Accounts OAuth profile endpoint — works for ALL Zoho users
              (requires AaaServer.profile.Read scope in the OAuth grant).
    Returns a normalised dict with a 'users' list to keep app.py logic unchanged.
    """
    headers = {'Authorization': f'Zoho-oauthtoken {access_token}'}

    # --- Primary: CRM Users API ---
    crm_url = f"{ZOHO_API_URL}/crm/v3/users?type=CurrentUser"
    try:
        resp = requests.get(crm_url, headers=headers, timeout=8)
        data = resp.json()
        if data.get('status') != 'error' and 'users' in data:
            return data
        print(f"[zoho_api] CRM users API failed: {data.get('code')} - trying accounts fallback")
    except Exception as e:
        print(f"[zoho_api] CRM users API exception: {e} - trying accounts fallback")

    # --- Fallback: Zoho Accounts OAuth profile ---
    profile_url = f"{ZOHO_ACCOUNTS_URL}/oauth/user/info"
    try:
        resp = requests.get(profile_url, headers=headers, timeout=8)
        print(f"[zoho_api] Accounts profile response [{resp.status_code}]: {resp.text[:300]}")
        profile = resp.json()
        if 'Email' in profile or 'Display_Name' in profile:
            full_name = profile.get('Display_Name') or (
                f"{profile.get('First_Name', '')} {profile.get('Last_Name', '')}".strip()
            )
            user_id = profile.get('ZAUID') or profile.get('Email', 'unknown')
            return {
                'users': [{
                    'id': str(user_id),
                    'full_name': full_name,
                    'last_name': profile.get('Last_Name', ''),
                    'profile': {'name': 'Standard', 'id': 'standard'}
                }]
            }
        print(f"[zoho_api] Accounts profile missing expected fields: {list(profile.keys())}")
    except Exception as e:
        print(f"[zoho_api] Accounts profile exception: {e}")

    return {'code': 'NO_PERMISSION', 'message': 'Could not fetch user info from any endpoint', 'status': 'error'}
