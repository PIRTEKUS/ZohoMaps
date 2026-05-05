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
        data['marker_color']
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

@app.route('/api/map-data')
def get_map_data():
    if 'access_token' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    log_debug("Fetching map data from Zoho...")
    configs = database.get_all_module_configs()
    map_points = []
    
    for config in configs:
        module_name = config['module_name']
        fields = config['field_mappings']
        
        # We need to fetch fields mapped for the address + a name field.
        fetch_fields = [f for f in fields.values() if f]
        if 'Name' not in fetch_fields and 'Full_Name' not in fetch_fields:
            # Attempt to fetch basic identifiers
            fetch_fields.extend(['id'])
            
        data = zoho_api.fetch_module_records(module_name, session['access_token'], fetch_fields)
        if 'data' not in data:
            log_debug(f"No data returned from Zoho API for module {module_name}. Response: {data}")
            continue
            
        for record in data['data']:
            lat, lng = None, None
            name = record.get('Name', record.get('Full_Name', f"{module_name} {record.get('id')}"))
            
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
                # Combine address fields
                address_parts = []
                for k in ['address1', 'address2', 'city', 'state', 'zip', 'country']:
                    val = record.get(fields.get(k))
                    if val:
                        address_parts.append(str(val))
                
                full_address = ", ".join(address_parts)
                if full_address:
                    lat, lng = geocode_address(full_address)
            
            if lat and lng:
                map_points.append({
                    'id': record.get('id'),
                    'module': module_name,
                    'name': name,
                    'lat': lat,
                    'lng': lng,
                    'color': config['marker_color'],
                    'record_data': {k: record.get(k) for k in fetch_fields}
                })

    log_debug(f"Finished loading {len(map_points)} records to map.")
    return jsonify(map_points)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
