from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from configparser import ConfigParser
import database
import zoho_api
import requests
import json
import time
import datetime
import os

config = ConfigParser()
config.read('config.ini')

app = Flask(__name__)
app.secret_key = config['APP'].get('secret_key', 'dev_key')
GOOGLE_MAPS_API_KEY = config['GOOGLE'].get('maps_api_key')

# Initialize Database
database.init_db()

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')

# Derive CRM base URL from API URL for record links
# Use crmplus.zoho.com as requested for CRM Plus/Zoho One environments
ZOHO_CRM_URL = "https://crmplus.zoho.com"
if "zohoapis.eu" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crmplus.zoho.eu"
elif "zohoapis.com.au" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crmplus.zoho.com.au"
elif "zohoapis.in" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crmplus.zoho.in"
elif "zohoapis.jp" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crmplus.zoho.jp"

def log_debug(msg):
    print(msg)
    try:
        with open(LOG_FILE, 'a') as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception as e:
        print(f"Error writing to {LOG_FILE}: {e}")

def extract_val(val):
    if isinstance(val, dict):
        return val.get('name', val.get('display_value', str(val)))
    return val

def geocode_address(address):
    cached = database.get_cached_geocode(address)
    if cached:
        return cached['lat'], cached['lng']
    
    log_debug(f"Geocoding new address (this may take a moment): {address}")
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(address)}&key={GOOGLE_MAPS_API_KEY}"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp.get('status') == 'OK' and len(resp.get('results', [])) > 0:
            loc = resp['results'][0]['geometry']['location']
            database.set_cached_geocode(address, loc['lat'], loc['lng'])
            log_debug(f"Success! Cached coordinates for {address}.")
            return loc['lat'], loc['lng']
        else:
            log_debug(f"Geocode failed for {address}: {resp.get('status')}")
    except Exception as e:
        log_debug(f"Error geocoding {address}: {e}")
    return None, None

@app.route('/api/logs')
def get_logs():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
            if not lines:
                return jsonify({'logs': ['Waiting for server activity...']})
            return jsonify({'logs': [line.strip() for line in lines[-50:]]})
    except FileNotFoundError:
        return jsonify({'logs': ['Waiting for server activity...']})

@app.route('/api/logs/clear', methods=['POST'])
def clear_server_logs():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        with open(LOG_FILE, 'w') as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] --- Logs cleared by {session.get('user_name')} ---\n")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.before_request
def check_token_refresh():
    if 'access_token' in session and 'expires_at' in session:

        # 1. Refresh token if near expiry
        if time.time() > session['expires_at'] - 300:
            if 'refresh_token' in session:
                token_data = zoho_api.refresh_access_token(session['refresh_token'])
                if 'access_token' in token_data:
                    session['access_token'] = token_data['access_token']
                    session['expires_at'] = time.time() + token_data.get('expires_in', 3600)

        # 2. Fetch user info if missing
        if 'user_id' not in session or 'is_admin' not in session:
            try:
                user_info = zoho_api.fetch_user_info(session['access_token'])
                if 'users' in user_info and len(user_info['users']) > 0:
                    user = user_info['users'][0]
                    session['user_id'] = user['id']
                    session['user_name'] = user.get('full_name', user.get('last_name', 'Zoho User'))
                    profile = user.get('profile', {})
                    profile_name = profile.get('name', '')
                    session['is_admin'] = (profile_name.lower() in ['administrator', 'admin'])
                    log_debug(f"LOGIN INFO: Name={session['user_name']}, Profile={profile_name}, IsAdmin={session['is_admin']}, ID={session['user_id']}")
            except Exception as e:
                log_debug(f"DEBUG: Failed to fetch user info: {str(e)}")

        # 3. Detect org/domain — runs INDEPENDENTLY for every user when missing from session
        if 'org_id' not in session or 'domain_name' not in session:
            org_fetched = False
            try:
                org_info = zoho_api.fetch_org_metadata(session['access_token'])
                log_debug(f"DEBUG Org API raw response keys: {list(org_info.keys())} | code={org_info.get('code','?')}")
                if 'org' in org_info and len(org_info['org']) > 0:
                    org = org_info['org'][0]
                    log_debug(f"DEBUG: Full Org Data: {json.dumps(org)}")
                    session['org_id'] = org.get('zgid') or org.get('zoid') or org.get('id')
                    session['domain_name'] = org.get('domain_name', '')
                    org_fetched = True
                    log_debug(f"AUTO-DETECTED: OrgID={session['org_id']}, Domain={session['domain_name']}")
                    if session['org_id'] and not database.get_global_setting('crmplus_orgid', ''):
                        database.set_global_setting('crmplus_orgid', str(session['org_id']))
                        log_debug(f"Saved OrgID to global settings: {session['org_id']}")
                    if session['domain_name'] and not database.get_global_setting('crmplus_domain', ''):
                        database.set_global_setting('crmplus_domain', session['domain_name'])
                        log_debug(f"Saved Domain to global settings: {session['domain_name']}")
                else:
                    # v6 failed — try v3 as fallback
                    log_debug(f"Org v6 failed (code={org_info.get('code','?')}), trying v3...")
                    org_info_v3 = zoho_api.fetch_org_metadata_v3(session['access_token'])
                    log_debug(f"DEBUG Org v3 raw: {json.dumps(org_info_v3)[:300]}")
                    if 'org' in org_info_v3 and len(org_info_v3['org']) > 0:
                        org = org_info_v3['org'][0]
                        session['org_id'] = org.get('zgid') or org.get('zoid') or org.get('id')
                        session['domain_name'] = org.get('domain_name', '')
                        org_fetched = True
                        log_debug(f"AUTO-DETECTED (v3): OrgID={session['org_id']}, Domain={session['domain_name']}")
                        if session['org_id'] and not database.get_global_setting('crmplus_orgid', ''):
                            database.set_global_setting('crmplus_orgid', str(session['org_id']))
                        if session['domain_name'] and not database.get_global_setting('crmplus_domain', ''):
                            database.set_global_setting('crmplus_domain', session['domain_name'])
            except Exception as org_err:
                log_debug(f"DEBUG: Org API exception: {str(org_err)}")

            # Fallback: load from global DB (written by admin session)
            if not org_fetched:
                stored_org_id = database.get_global_setting('crmplus_orgid', '')
                stored_domain  = database.get_global_setting('crmplus_domain', '')
                if stored_org_id:
                    session['org_id'] = stored_org_id
                    log_debug(f"Loaded OrgID from global settings: {stored_org_id}")
                if stored_domain:
                    session['domain_name'] = stored_domain
                    log_debug(f"Loaded Domain from global settings: {stored_domain}")
                if not stored_org_id and not stored_domain:
                    log_debug("WARNING: org/domain not found via API or global settings. Admin must log in or set manually in Settings.")


@app.route('/')
def index():
    if 'access_token' not in session or not session.get('user_id'):
        return redirect(url_for('login'))
    
    # Priority: Manual Global Setting > Session Cache
    org_id = database.get_global_setting('crmplus_orgid', '') or session.get('org_id', 'Unknown')
    domain_name = database.get_global_setting('crmplus_domain', '') or session.get('domain_name', 'Unknown')
    is_manual = database.get_global_setting('crmplus_orgid', '') != '' or database.get_global_setting('crmplus_domain', '') != ''
    
    log_debug(f"--- MAP SESSION CONNECTED ---")
    log_debug(f"User: {session.get('user_name')} ({'Administrator' if session.get('is_admin') else 'Standard User'})")
    log_debug(f"CRM Plus Config: Domain={domain_name}, OrgID={org_id} ({'Manual Override' if is_manual else 'Auto-Detected'})")
    
    # show_console is a per-user session setting — admins can toggle it in Settings;
    # it is intentionally NOT a global setting so team users never see the console.
    show_console = session.get('show_console', False) and session.get('is_admin', False)
    effective_configs = database.get_effective_configs(session.get('user_id'))
    return render_template('map.html', google_maps_api_key=GOOGLE_MAPS_API_KEY, show_console=show_console, configs=effective_configs)

@app.route('/login')
def login():
    # Dynamically select the redirect URI matching the current request host
    matched_uri = zoho_api.get_matching_redirect_uri(request.host_url)
    auth_url = zoho_api.get_authorization_url(redirect_uri=matched_uri)
    log_debug(f"Login initiated — using redirect_uri: {matched_uri}")
    return render_template('login.html', auth_url=auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if code:
        # Pick the redirect URI that matches the host the callback arrived on
        matched_uri = zoho_api.get_matching_redirect_uri(request.host_url)
        log_debug(f"OAuth callback received — using redirect_uri: {matched_uri}")
        token_data = zoho_api.exchange_code_for_token(code, redirect_uri=matched_uri)
        if 'access_token' in token_data:
            session['access_token'] = token_data['access_token']
            session['expires_at'] = time.time() + token_data.get('expires_in', 3600)
            if 'refresh_token' in token_data:
                session['refresh_token'] = token_data['refresh_token']
            
            # Fetch User Info to identify them uniquely
            user_info = zoho_api.fetch_user_info(session['access_token'])
            log_debug(f"DEBUG: Callback Raw user_info: {user_info}")
            if 'users' in user_info and len(user_info['users']) > 0:
                user = user_info['users'][0]
                session['user_id'] = user['id']
                session['user_name'] = user.get('full_name', user.get('last_name', 'Zoho User'))
                session['is_admin'] = user.get('profile', {}).get('name') == 'Administrator'
                log_debug(f"User logged in: {session['user_name']} ({session['user_id']}) - Admin: {session.get('is_admin')}")
                
                # Cache the admin's refresh_token globally so it can be used as a fallback
                # for team users who lack API scope (CRM profile API access disabled).
                # SECURITY: This token is ONLY used server-side, never exposed to the frontend.
                if session['is_admin'] and 'refresh_token' in token_data:
                    database.set_global_setting('admin_refresh_token', token_data['refresh_token'])
                    log_debug("Admin refresh token cached for team user fallback sync.")
                
                # If user logged in via email fallback, try to resolve their real numeric CRM user ID
                # using the admin token. This is needed for the Owner.id filter in the fallback sync.
                if not session.get('is_admin') and '@' in str(session.get('user_id', '')):
                    try:
                        admin_token = _get_admin_access_token()
                        if admin_token:
                            user_email = session['user_id']
                            all_users = requests.get(
                                f"{zoho_api.ZOHO_API_URL}/crm/v3/users?type=AllUsers",
                                headers={'Authorization': f'Zoho-oauthtoken {admin_token}'},
                                timeout=8
                            ).json()
                            if 'users' in all_users:
                                for u in all_users['users']:
                                    if u.get('email', '').lower() == user_email.lower():
                                        session['user_id'] = u['id']
                                        session['user_email'] = user_email
                                        log_debug(f"Resolved team user email {user_email} -> CRM ID {u['id']}")
                                        break
                    except Exception as e:
                        log_debug(f"Could not resolve team user CRM ID: {e}")

                
            return redirect(url_for('index'))
    return "Error in Zoho Authentication", 400

@app.route('/logout')
def logout():
    # Revoke the token at Zoho's server BEFORE clearing the session.
    # This forces a fresh consent screen on next login so all current scopes are re-granted.
    # Without this, Zoho continues issuing tokens with OLD limited scopes even after re-login.
    refresh_token = session.get('refresh_token')
    if refresh_token:
        try:
            zoho_api.revoke_token(refresh_token)
            log_debug(f"OAuth token revoked for user: {session.get('user_name', 'unknown')}")
        except Exception as e:
            log_debug(f"Token revocation failed (non-fatal): {e}")
    session.clear()
    return redirect(url_for('login'))

@app.route('/settings')
def settings():
    if 'access_token' not in session:
        return redirect(url_for('login'))
    # Team users don't need settings — redirect them to the map
    if not session.get('is_admin', False):
        return redirect(url_for('index'))
    configs = database.get_all_module_configs(session.get('user_id'))
    shared_configs = database.get_shared_configs()
    show_console = database.get_global_setting('show_console', 'false') == 'true'
    crm_domain = database.get_global_setting('crmplus_domain', '')
    crm_org_id = database.get_global_setting('crmplus_orgid', '')
    is_admin = session.get('is_admin', False)
    return render_template('settings.html', 
                           configs=configs, 
                           shared_configs=shared_configs,
                           show_console=show_console,
                           crm_domain=crm_domain,
                           crm_org_id=crm_org_id,
                           is_admin=is_admin)

@app.route('/api/modules')
def get_modules():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    metadata = zoho_api.fetch_module_metadata(session['access_token'])
    if 'modules' in metadata:
        modules = [{'api_name': m['api_name'], 'plural_label': m['plural_label']} for m in metadata['modules']]
        # Cache in DB so team users (who lack ZohoCRM.settings.all) can use it
        database.set_global_setting('cached_modules', json.dumps(modules))
        return jsonify(modules)
    
    # Fallback: serve cached module list written by an admin session
    cached = database.get_global_setting('cached_modules', '')
    if cached:
        log_debug("Serving cached module list for user without settings permission")
        return jsonify(json.loads(cached))
    
    log_debug(f"Module fetch failed: {metadata.get('code', '?')} - {metadata.get('message', '?')}")
    return jsonify({'error': 'Failed to fetch modules'}), 500

@app.route('/api/fields/<module_name>')
def get_fields(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    metadata = zoho_api.fetch_module_fields(module_name, session['access_token'])
    if 'fields' in metadata:
        fields = [{'api_name': f['api_name'], 'display_label': f['display_label']} for f in metadata['fields']]
        # Cache per-module fields so team users can use them too
        database.set_global_setting(f'cached_fields_{module_name}', json.dumps(fields))
        return jsonify(fields)
    
    # Fallback: serve cached fields
    cached = database.get_global_setting(f'cached_fields_{module_name}', '')
    if cached:
        log_debug(f"Serving cached fields for {module_name} (no settings permission)")
        return jsonify(json.loads(cached))
    
    log_debug(f"Fields fetch failed for {module_name}: {metadata.get('code','?')}")
    return jsonify({'error': 'Failed to fetch fields'}), 500

@app.route('/api/settings/config', methods=['POST'])
def save_config():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    try:
        database.save_module_config(
            user_id=session.get('user_id'),
            module_name=data['module_name'],
            location_type='both',
            field_mappings=data['field_mappings'],
            marker_color=data['marker_color'],
            marker_icon=data.get('marker_icon', 'pin'),
            is_shared=data.get('is_shared', False)
        )
        return jsonify({'success': True})
    except Exception as e:
        log_debug(f"Error saving config: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/settings/config/<module_name>', methods=['DELETE'])
def delete_config(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    database.delete_module_config(session.get('user_id'), module_name)
    database.clear_module_records(session.get('user_id'), module_name)
    return jsonify({'success': True})

@app.route('/api/settings/global', methods=['POST'])
def save_global_setting():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not session.get('is_admin', False):
        return jsonify({'error': 'Admin only'}), 403
    data = request.json
    key = data.get('key', '')
    value = data.get('value', '')

    # show_console is a per-user (session) setting, NOT a global DB setting.
    # Storing it globally would enable the console for ALL users, including
    # team users who should never see internal debug output.
    if key == 'show_console':
        session['show_console'] = (value == 'true')
        return jsonify({'success': True})

    # All other keys (crmplus_domain, crmplus_orgid, etc.) are admin-only globals
    database.set_global_setting(key, value)
    return jsonify({'success': True})




@app.route('/api/preview-record/<module_name>')
def preview_record(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Fetch 1 record to use for preview. We don't specify fields so we get all fields.
    data = zoho_api.fetch_module_records(module_name, session['access_token'], page=1)
    if 'data' not in data or len(data['data']) == 0:
        return jsonify({'error': 'No records found'}), 404
        
    return jsonify(data['data'][0])



def _get_admin_access_token():
    """Get a fresh admin access token from the cached refresh token.
    Used ONLY as a server-side fallback when team users cannot call the CRM API
    due to their CRM Profile having API Access disabled.
    The admin token is NEVER exposed to the frontend or sent to the client."""
    refresh_token = database.get_global_setting('admin_refresh_token', '')
    if not refresh_token:
        return None
    try:
        token_data = zoho_api.refresh_access_token(refresh_token)
        if 'access_token' in token_data:
            return token_data['access_token']
        log_debug(f"Admin token refresh failed: {token_data.get('error', 'unknown error')}")
    except Exception as e:
        log_debug(f"Admin token refresh exception: {e}")
    return None


def do_sync_module(user_id, access_token, module_name, config):
    """Core logic to fetch, geocode, and save records for a single module."""
    log_debug(f"Starting sync for module: {module_name} for user {user_id}...")
    database.clear_module_records(user_id, module_name)
    
    fields = config['field_mappings']
    
    fetch_fields = set()
    for k, v in fields.items():
        if k == 'additional_fields' and isinstance(v, list):
            fetch_fields.update([f for f in v if f])
        elif isinstance(v, str) and v:
            fetch_fields.add(v)
            
    title_field = fields.get('title_field')
    
    if title_field:
        name_field = title_field
    else:
        name_field = 'Name'
        if module_name == 'Accounts':
            name_field = 'Account_Name'
        elif module_name == 'Leads' or module_name == 'Contacts':
            name_field = 'Full_Name'
            
    fetch_fields.add(name_field)
    fetch_fields.add('id')
    
    fetch_fields_list = list(fetch_fields)
        
    # Get field labels for display
    field_metadata = zoho_api.fetch_module_fields(module_name, access_token)
    field_label_map = {}
    if 'fields' in field_metadata:
        for f in field_metadata['fields']:
            field_label_map[f['api_name']] = f['display_label']
        # Automatically cache fields for team user fallback
        try:
            fields_to_cache = [{'api_name': f['api_name'], 'display_label': f['display_label']} for f in field_metadata['fields']]
            database.set_global_setting(f'cached_fields_{module_name}', json.dumps(fields_to_cache))
        except Exception as e:
            log_debug(f"Failed to cache fields for {module_name}: {e}")
    else:
        # Team users lack permission to fetch fields, so fallback to the admin's globally cached fields
        cached = database.get_global_setting(f'cached_fields_{module_name}', '')
        if cached:
            try:
                cached_fields = json.loads(cached)
                for f in cached_fields:
                    field_label_map[f['api_name']] = f['display_label']
            except:
                pass
        
        log_debug(f"Warning: No 'fields' key in metadata for {module_name}. Response keys: {list(field_metadata.keys())}")
        if 'code' in field_metadata:
            log_debug(f"Metadata error: {field_metadata.get('code')} - {field_metadata.get('message')}")
    
    log_debug(f"Mapped {len(field_label_map)} labels for {module_name}. Samples: {list(field_label_map.keys())[:5]}")
        
    count = 0
    page = 1
    page_token = None
    more_records = True
    
    while more_records:
        log_debug(f"Fetching page {page} for {module_name}...")
        
        # We restore fetch_fields_list because omitting it seems to cause Zoho to return 0 records or an error for everyone.
        data = zoho_api.fetch_module_records(module_name, access_token, fetch_fields_list, page=page, page_token=page_token)
        
        if 'code' in data and data.get('status') == 'error':
            error_code = data.get('code')
            log_debug(f"API Error fetching {module_name}: {error_code} - {data.get('message')}")
            
            # If NO_PERMISSION, try fetching with minimal fields to determine if it's FLS or Scope/Module Access
            if error_code == 'NO_PERMISSION':
                log_debug(f"Testing minimal fields (id, {name_field}) for {module_name} to check FLS...")
                minimal_data = zoho_api.fetch_module_records(module_name, access_token, ['id', name_field], page=page, page_token=page_token)
                if 'code' in minimal_data and minimal_data.get('status') == 'error':
                    log_debug(f"Minimal fields ALSO FAILED for {module_name}. CRM Profile has API Access disabled. Attempting admin-token fallback...")
                    
                    # ─────────────────────────────────────────────────────────────────────
                    # ADMIN TOKEN FALLBACK for Team Users with API Access disabled in CRM
                    #
                    # DATA PRIVACY RULES:
                    # 1. We ONLY fetch records where Owner.id == the team user's Zoho user ID.
                    #    The admin token gives broad access, but filtering by owner ensures
                    #    the team user ONLY sees their own assigned records.
                    # 2. Records are saved under the team user's user_id — never the admin's.
                    # 3. This fallback is ONLY triggered when the user's own token fails.
                    # ─────────────────────────────────────────────────────────────────────
                    admin_token = _get_admin_access_token()
                    if admin_token and user_id:
                        log_debug(f"Using admin token to fetch {module_name} records owned by {user_id}")
                        # Build owner criteria: only records assigned to this user
                        criteria = f"(Owner.id:equals:{user_id})"
                        owner_data = zoho_api.search_records(module_name, criteria, admin_token, fields=fetch_fields_list)
                        if 'data' in owner_data and owner_data['data']:
                            data = owner_data
                            log_debug(f"Admin fallback returned {len(owner_data['data'])} records for {module_name} owned by {user_id}")
                        else:
                            log_debug(f"Admin fallback returned 0 records for {module_name} owned by {user_id}. Either no records assigned, or criteria filter failed.")
                            break
                    else:
                        log_debug(f"No admin token available for fallback. Admin must log in first.")
                        break
                else:
                    log_debug(f"Minimal fields SUCCEEDED for {module_name}! FLS issue — user cannot view one of: {fetch_fields_list}")
                    break
            else:
                break
            
        if 'data' not in data or not data['data']:
            break
            
        page_records = []
        for record in data['data']:
            lat, lng = None, None
            name_raw = record.get(name_field, record.get('Full_Name', record.get('Name', f"{module_name} {record.get('id')}")))
            name = str(extract_val(name_raw))
            
            # Prioritize Coordinates if available
            lat_field = fields.get('latitude')
            lng_field = fields.get('longitude')
            if lat_field and lng_field and record.get(lat_field) and record.get(lng_field):
                try:
                    lat = float(record[lat_field])
                    lng = float(record[lng_field])
                except (ValueError, TypeError):
                    pass
            
            # Fallback to Address if Coordinates failed or were missing
            if lat is None or lng is None:
                address_parts = []
                for k in ['address1', 'address2', 'city', 'state', 'zip', 'country']:
                    val = extract_val(record.get(fields.get(k)))
                    if val:
                        address_parts.append(str(val))
                
                full_address = ", ".join(address_parts)
                if full_address:
                    lat, lng = geocode_address(full_address)
            
            if lat is not None and lng is not None:
                record_data = {}
                
                # Add location info
                lat_val = record.get(fields.get('latitude'))
                lng_val = record.get(fields.get('longitude'))
                if lat_val: record_data['Latitude'] = str(lat_val)
                if lng_val: record_data['Longitude'] = str(lng_val)

                addr1 = extract_val(record.get(fields.get('address1')))
                addr2 = extract_val(record.get(fields.get('address2')))
                full_addr = f"{addr1 or ''} {addr2 or ''}".strip()
                if full_addr: record_data['Address'] = full_addr
                
                for k, label in [('city', 'City'), ('state', 'State'), ('zip', 'Zip'), ('country', 'Country')]:
                    val = extract_val(record.get(fields.get(k)))
                    if val: record_data[label] = str(val)


                # 2. Add additional fields
                for k in fetch_fields_list:
                    # Skip fields we already handled or standard IDs
                    if k in ['id', name_field] or k in fields.values():
                        continue
                    
                    val = record.get(k)
                    if val:
                        label = field_label_map.get(k, k.replace('_', ' '))
                        record_data[label] = str(extract_val(val))
                        
                page_records.append((
                    record.get('id'),
                    module_name,
                    name,
                    lat,
                    lng,
                    config['marker_color'],
                    record_data
                ))
                count += 1
            else:
                log_debug(f"Skipping record {record.get('id')} ({name}): No valid location found.")

        # Batch save the current page
        if page_records:
            database.save_module_records_batch(user_id, page_records)

        # Check for more records
        info = data.get('info', {})
        more_records = info.get('more_records', False)
        page_token = info.get('next_page_token')
        
        if more_records:
            page += 1
        
        # Extended safety break: 500 pages * 200 = 100,000 records max per module
        if page > 500:
            break

    log_debug(f"Sync complete! Saved {count} records for {module_name} (User: {user_id}).")
    return count

@app.route('/api/sync-module/<module_name>', methods=['POST'])
def sync_module(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Use effective configs so admins and team users can sync shared configs manually if needed
    configs = database.get_effective_configs(session.get('user_id'))
    config = next((c for c in configs if c['module_name'] == module_name), None)
    if not config:
        return jsonify({'error': 'Module not configured'}), 404
        
    try:
        count = do_sync_module(session.get('user_id'), session['access_token'], module_name, config)
        return jsonify({'success': True, 'synced': count})
    except Exception as e:
        log_debug(f"Sync error for {module_name}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sync-all', methods=['POST'])
def sync_all_modules():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Use effective configs so team users can sync shared configs
    configs = database.get_effective_configs(session.get('user_id'))
    if not configs:
        return jsonify({'error': 'No modules configured to sync'}), 404
        
    results = {}
    total_synced = 0
    
    for config in configs:
        module_name = config['module_name']
        try:
            count = do_sync_module(session.get('user_id'), session['access_token'], module_name, config)
            results[module_name] = {'success': True, 'synced': count}
            total_synced += count
        except Exception as e:
            results[module_name] = {'error': str(e)}
            
    return jsonify({'success': True, 'total_synced': total_synced, 'details': results})



def sync_records_by_bounds(user_id, access_token, min_lat, max_lat, min_lng, max_lng):
    """
    Background sync for records in the current map viewport.

    DATA PRIVACY RULES — DO NOT CHANGE WITHOUT REVIEW:
    ────────────────────────────────────────────────────────────
    1. Records are fetched using the CALLER'S OWN access_token.
       Zoho enforces field-level and record-level CRM permissions on
       their side — the API will only return records the user can see.
    2. Records are ALWAYS saved under the caller's own user_id.
       Never save another user's records under a different user_id.
    3. get_effective_configs is used here ONLY to determine WHICH
       MODULES to sync (display configuration / field mappings).
       It does NOT grant access to another user's DATA.
    ────────────────────────────────────────────────────────────
    """
    # get_effective_configs returns the user's own configs merged with any
    # shared module configurations (field mappings, colors, etc.).
    # This tells us WHAT to sync — not WHOSE data to show.
    configs = database.get_effective_configs(user_id)
    total_new = 0
    
    for config in configs:
        module_name = config['module_name']
        fields = config['field_mappings']
        lat_field = fields.get('latitude')
        lng_field = fields.get('longitude')
        
        # Only modules with mapped lat/lng in Zoho can be searched by area
        if not lat_field or not lng_field:
            continue
            
        try:
            # Construct criteria: (Lat > min) AND (Lat < max) AND (Lng > min) AND (Lng < max)
            # Note: Criteria syntax might vary, using standard Zoho V3 pattern
            criteria = f"(({lat_field}:greater_than:{min_lat}) AND ({lat_field}:less_than:{max_lat}) AND ({lng_field}:greater_than:{min_lng}) AND ({lng_field}:less_than:{max_lng}))"
            
            # Fetch fields needed
            fetch_fields = set(['id', fields.get('title_field', 'Name')])
            for k, v in fields.items():
                if k == 'additional_fields' and isinstance(v, list):
                    fetch_fields.update([f for f in v if f])
                elif isinstance(v, str) and v:
                    fetch_fields.add(v)

            
            data = zoho_api.search_records(module_name, criteria, access_token, fields=list(fetch_fields))
            
            if 'data' not in data or not data['data']:
                continue
                
            new_records = []
            for record in data['data']:
                # Basic processing (similar to full sync but lighter)
                name_field = fields.get('title_field', 'Name')
                name = str(extract_val(record.get(name_field, '')))
                
                try:
                    lat = float(record[lat_field])
                    lng = float(record[lng_field])
                except:
                    continue # Skip if no valid coords returned
                
                # Build record_data for popup
                record_data = {}
                for k, v in record.items():
                    if k not in ['id', '$', 'Entity_Id']:
                        record_data[k] = str(extract_val(v))
                
                new_records.append((
                    record['id'],
                    module_name,
                    name,
                    lat,
                    lng,
                    config['marker_color'],
                    record_data
                ))
            
            if new_records:
                database.save_module_records_batch(user_id, new_records)
                total_new += len(new_records)
                
        except Exception as e:
            log_debug(f"Error in area-sync for {module_name}: {str(e)}")
            
    log_debug(f"Area sync finished. Added/Updated {total_new} records from Zoho.")
    return total_new

@app.route('/api/map-data')
def get_map_data():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    min_lat = float(request.args.get('min_lat', -90))
    max_lat = float(request.args.get('max_lat', 90))
    min_lng = float(request.args.get('min_lng', -180))
    max_lng = float(request.args.get('max_lng', 180))
    do_sync = request.args.get('sync', 'false').lower() == 'true'
    
    if do_sync:
        # Use sync-specific bounds if provided (capped at 200 miles by frontend)
        s_min_lat = float(request.args.get('sync_min_lat', min_lat))
        s_max_lat = float(request.args.get('sync_max_lat', max_lat))
        s_min_lng = float(request.args.get('sync_min_lng', min_lng))
        s_max_lng = float(request.args.get('sync_max_lng', max_lng))
        
        try:
            log_debug(f"Triggering background area-sync for user: {session.get('user_id')} (Capped Area: {s_min_lat} to {s_max_lat})")
            sync_records_by_bounds(session.get('user_id'), session['access_token'], s_min_lat, s_max_lat, s_min_lng, s_max_lng)
        except Exception as e:
            log_debug(f"WARNING: Area sync failed but continuing with local data: {str(e)}")
    
    log_debug(f"Querying local cache for area: Lat({min_lat} to {max_lat}), Lng({min_lng} to {max_lng}) (User: {session.get('user_id')})")
    
    # =========================================================================
    # DATA PRIVACY — CRITICAL: Records are ALWAYS scoped to the requesting
    # user's own user_id. We never mix records across users, regardless of
    # shared configurations or admin status. Shared configs define DISPLAY
    # settings only (which modules/fields to show, colors, icons). They do
    # NOT grant access to another user's synced record data.
    # If this line is changed to include other user_ids, it WILL expose
    # one user's CRM data to another user. Do not change without full review.
    # =========================================================================
    records = database.get_records_in_bounds(
        session.get('user_id'), min_lat, max_lat, min_lng, max_lng
    )
    

    log_debug(f"Found {len(records)} records in bounds.")
    
    # Get module labels and org info for display
    module_metadata = zoho_api.fetch_module_metadata(session['access_token'])
    # Priority: Manual Global Setting > Session Cache > Fresh API Fetch
    org_id = database.get_global_setting('crmplus_orgid', '') or session.get('org_id', '')
    domain_name = database.get_global_setting('crmplus_domain', '') or session.get('domain_name', '')
    
    # Only fetch from Zoho if still missing
    if not org_id or not domain_name:
        try:
            org_metadata = zoho_api.fetch_org_metadata(session['access_token'])
            if 'org' in org_metadata and len(org_metadata['org']) > 0:
                org = org_metadata['org'][0]
                if not org_id: org_id = org['zoid']
                if not domain_name: domain_name = org.get('domain_name', '')
        except:
            pass
            
    log_debug(f"DEBUG: Using OrgID={org_id}, Domain={domain_name}")

    module_label_map = {}
    module_url_map = {} # Map api_name to URL segment
    if 'modules' in module_metadata:
        for m in module_metadata['modules']:
            module_label_map[m['api_name']] = m['plural_label']
            # If it's a custom module, we might need a different identifier for the URL
            if m.get('generated_type') == 'custom':
                module_url_map[m['api_name']] = m['api_name'] # Default
                for key, value in m.items():
                    if isinstance(value, str) and 'CustomModule' in value:
                        module_url_map[m['api_name']] = value
                        break
            else:
                module_url_map[m['api_name']] = m['api_name']

    # Build a config lookup dict: for team users this includes shared configs automatically
    configs = {c['module_name']: c for c in database.get_effective_configs(session.get('user_id'))}
    

    map_points = []
    for r in records:
        cfg = configs.get(r['module_name'], {})
        
        # Build robust link for CRM Plus / CX App
        link_module = module_url_map.get(r['module_name'], r['module_name'])
        if org_id:
            # Prefix org_id with 'org' if it's purely numeric
            safe_org_id = f"org{org_id}" if str(org_id).isdigit() else org_id
            
            if domain_name:
                # Modern CRM Plus / CX App format: /pirtekus/index.do/cxapp/crm/org897316137/tab/Leads/...
                zoho_link = f"{ZOHO_CRM_URL}/{domain_name}/index.do/cxapp/crm/{safe_org_id}/tab/{link_module}/{r['id']}"
            else:
                zoho_link = f"{ZOHO_CRM_URL}/{safe_org_id}/crm/tab/{link_module}/{r['id']}"
        else:
            zoho_link = f"{ZOHO_CRM_URL}/crm/tab/{link_module}/{r['id']}"

        map_points.append({
            'id': r['id'],
            'module': module_label_map.get(r['module_name'], r['module_name']),
            'zoho_link': zoho_link,
            'name': r['name'],
            'lat': r['lat'],
            'lng': r['lng'],
            'color': r['color'],
            'icon': cfg.get('marker_icon', 'pin'),
            'record_data': r['record_data']
        })

    return jsonify(map_points)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
