import json
from configparser import ConfigParser
import database

# Mock the settings and configs
def test_overrides():
    # 1. Set global database setting
    print("Setting database override: ShipToAddress -> CustomModule2")
    database.set_global_setting('module_url_overrides', json.dumps({'ShipToAddress': 'CustomModule2'}))
    
    # 2. Verify reading from DB
    db_overrides_str = database.get_global_setting('module_url_overrides', '{}')
    db_overrides = json.loads(db_overrides_str)
    print(f"Loaded from DB: {db_overrides}")
    assert db_overrides.get('ShipToAddress') == 'CustomModule2', "DB override failed"

    # Test config-based override loading
    config = ConfigParser()
    config.read_string("""
[MODULE_URL_OVERRIDES]
ShipToAddress = CustomModule2
""")
    url_overrides = {}
    if config.has_section('MODULE_URL_OVERRIDES'):
        for key, value in config['MODULE_URL_OVERRIDES'].items():
            url_overrides[str(key)] = str(value)
            url_overrides[str(key).lower()] = str(value)
            
    print(f"Loaded from Config: {url_overrides}")
    assert url_overrides.get('shiptoaddress') == 'CustomModule2', "Config override failed"
    print("All tests passed successfully!")

if __name__ == '__main__':
    test_overrides()
