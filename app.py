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
ZOHO_CRM_URL = "https://crm.zoho.com"
if "zohoapis.eu" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crm.zoho.eu"
elif "zohoapis.com.au" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crm.zoho.com.au"
elif "zohoapis.in" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crm.zoho.in"
elif "zohoapis.jp" in zoho_api.ZOHO_API_URL: ZOHO_CRM_URL = "https://crm.zoho.jp"

def log_debug(msg):
    print(msg)
    try:
        with open(LOG_FILE, 'a') as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception as e:
        print(f"Error writing to {LOG_FILE}: {e}")

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


@app.before_request
def check_token_refresh():
    if 'access_token' in session and 'expires_at' in session:
        if time.time() > session['expires_at'] - 300: # Refresh if within 5 mins of expiry
            if 'refresh_token' in session:
                token_data = zoho_api.refresh_access_token(session['refresh_token'])
                if 'access_token' in token_data:
                    session['access_token'] = token_data['access_token']
                    session['expires_at'] = time.time() + token_data.get('expires_in', 3600)

@app.route('/')
def index():
    if 'access_token' not in session:
        return redirect(url_for('login'))
    show_console = database.get_global_setting('show_console', 'false') == 'true'
    return render_template('map.html', google_maps_api_key=GOOGLE_MAPS_API_KEY, show_console=show_console)

@app.route('/login')
def login():
    auth_url = zoho_api.get_authorization_url()
    return render_template('login.html', auth_url=auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if code:
        token_data = zoho_api.exchange_code_for_token(code)
        if 'access_token' in token_data:
            session['access_token'] = token_data['access_token']
            session['expires_at'] = time.time() + token_data.get('expires_in', 3600)
            if 'refresh_token' in token_data:
                session['refresh_token'] = token_data['refresh_token']
            return redirect(url_for('index'))
    return "Error in Zoho Authentication", 400

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/settings')
def settings():
    if 'access_token' not in session:
        return redirect(url_for('login'))
    configs = database.get_all_module_configs()
    show_console = database.get_global_setting('show_console', 'false') == 'true'
    return render_template('settings.html', configs=configs, show_console=show_console)

@app.route('/api/modules')
def get_modules():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    metadata = zoho_api.fetch_module_metadata(session['access_token'])
    if 'modules' in metadata:
        modules = [{'api_name': m['api_name'], 'plural_label': m['plural_label']} for m in metadata['modules']]
        return jsonify(modules)
    return jsonify({'error': 'Failed to fetch modules'}), 500

@app.route('/api/fields/<module_name>')
def get_fields(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    metadata = zoho_api.fetch_module_fields(module_name, session['access_token'])
    if 'fields' in metadata:
        fields = [{'api_name': f['api_name'], 'display_label': f['display_label']} for f in metadata['fields']]
        return jsonify(fields)
    return jsonify({'error': 'Failed to fetch fields'}), 500

@app.route('/api/settings/config', methods=['POST'])
def save_config():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    database.save_module_config(
        data['module_name'],
        data['location_type'],
        data['field_mappings'],
        data['marker_color'],
        data.get('marker_icon', 'pin')
    )
    return jsonify({'success': True})

@app.route('/api/settings/config/<module_name>', methods=['DELETE'])
def delete_config(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    database.delete_module_config(module_name)
    return jsonify({'success': True})

@app.route('/api/settings/global', methods=['POST'])
def save_global_setting():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    database.set_global_setting(data['key'], data['value'])
    return jsonify({'success': True})

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

@app.route('/api/preview-record/<module_name>')
def preview_record(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Fetch 1 record to use for preview. We don't specify fields so we get all fields.
    data = zoho_api.fetch_module_records(module_name, session['access_token'], page=1)
    if 'data' not in data or len(data['data']) == 0:
        return jsonify({'error': 'No records found'}), 404
        
    return jsonify(data['data'][0])

@app.route('/api/sync-module/<module_name>', methods=['POST'])
def sync_module(module_name):
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    config = database.get_module_config(module_name)
    if not config:
        return jsonify({'error': 'Module not configured'}), 404
        
    log_debug(f"Starting sync for module: {module_name}...")
    database.clear_module_records(module_name)
    
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
    field_metadata = zoho_api.fetch_module_fields(module_name, session['access_token'])
    field_label_map = {}
    if 'fields' in field_metadata:
        for f in field_metadata['fields']:
            field_label_map[f['api_name']] = f['display_label']
    else:
        log_debug(f"Warning: No 'fields' key in metadata for {module_name}. Response keys: {list(field_metadata.keys())}")
        if 'code' in field_metadata:
            log_debug(f"Metadata error: {field_metadata.get('code')} - {field_metadata.get('message')}")
    
    log_debug(f"Mapped {len(field_label_map)} labels for {module_name}. Samples: {list(field_label_map.keys())[:5]}")

    # In a production app, we would paginate until no more data.
    # For now, we fetch one large page (200 records).
    data = zoho_api.fetch_module_records(module_name, session['access_token'], fetch_fields_list)
    if 'data' not in data:
        log_debug(f"No data returned from Zoho API for module {module_name}. Response: {data}")
        return jsonify({'success': True, 'synced': 0})
        
    def extract_val(val):
        if isinstance(val, dict):
            return val.get('name', val.get('display_value', str(val)))
        return val
        
    count = 0
    for record in data['data']:
        lat, lng = None, None
        name_raw = record.get(name_field, record.get('Full_Name', record.get('Name', f"{module_name} {record.get('id')}")))
        name = str(extract_val(name_raw))
        
        if config['location_type'] == 'coordinates':
            lat_field = fields.get('latitude')
            lng_field = fields.get('longitude')
            if lat_field and lng_field and record.get(lat_field) and record.get(lng_field):
                try:
                    lat = float(record[lat_field])
                    lng = float(record[lng_field])
                except ValueError:
                    pass
        else:
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
            
            # 1. Add location info in the requested order
            if config['location_type'] == 'address':
                addr1 = extract_val(record.get(fields.get('address1')))
                addr2 = extract_val(record.get(fields.get('address2')))
                full_addr = f"{addr1 or ''} {addr2 or ''}".strip()
                if full_addr: record_data['Address'] = full_addr
                
                for k, label in [('city', 'City'), ('state', 'State'), ('zip', 'Zip'), ('country', 'Country')]:
                    val = extract_val(record.get(fields.get(k)))
                    if val: record_data[label] = str(val)
            else:
                lat_val = record.get(fields.get('latitude'))
                lng_val = record.get(fields.get('longitude'))
                if lat_val: record_data['Latitude'] = str(lat_val)
                if lng_val: record_data['Longitude'] = str(lng_val)

            # 2. Add additional fields
            for k in fetch_fields_list:
                # Skip fields we already handled or standard IDs
                if k in ['id', name_field] or k in fields.values():
                    continue
                
                val = record.get(k)
                if val:
                    label = field_label_map.get(k, k.replace('_', ' '))
                    record_data[label] = str(extract_val(val))
                    
            database.save_module_record(
                id=record.get('id'),
                module_name=module_name,
                name=name,
                lat=lat,
                lng=lng,
                color=config['marker_color'],
                record_data=record_data
            )
            count += 1
        else:
            log_debug(f"Skipping record {record.get('id')} ({name}): No valid location found.")

    log_debug(f"Sync complete! Saved {count} records for {module_name}.")
    return jsonify({'success': True, 'synced': count})

@app.route('/api/map-data')
def get_map_data():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    min_lat = float(request.args.get('min_lat', -90))
    max_lat = float(request.args.get('max_lat', 90))
    min_lng = float(request.args.get('min_lng', -180))
    max_lng = float(request.args.get('max_lng', 180))
    
    log_debug(f"Querying local cache for area: Lat({min_lat} to {max_lat}), Lng({min_lng} to {max_lng})")
    
    records = database.get_records_in_bounds(min_lat, max_lat, min_lng, max_lng)
    
    log_debug(f"Found {len(records)} records in bounds.")
    
    # Get module labels and org info for display
    module_metadata = zoho_api.fetch_module_metadata(session['access_token'])
    org_metadata = zoho_api.fetch_org_metadata(session['access_token'])
    
    org_id = ""
    if 'org' in org_metadata and len(org_metadata['org']) > 0:
        org_id = org_metadata['org'][0]['zoid']

    module_label_map = {}
    if 'modules' in module_metadata:
        for m in module_metadata['modules']:
            module_label_map[m['api_name']] = m['plural_label']

    # Build a config lookup dict once to avoid per-record DB queries
    configs = {c['module_name']: c for c in database.get_all_module_configs()}
    
    map_points = []
    for r in records:
        cfg = configs.get(r['module_name'], {})
        
        # Build robust link
        link_module = r['module_name']
        zoho_link = f"{ZOHO_CRM_URL}/crm/tab/{link_module}/{r['id']}"
        if org_id:
            zoho_link = f"{ZOHO_CRM_URL}/crm/org{org_id}/tab/{link_module}/{r['id']}"

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
