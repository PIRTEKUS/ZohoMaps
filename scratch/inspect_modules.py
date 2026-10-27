import os
from database import get_global_setting
from app import decrypt_token
import zoho_api

def main():
    encrypted = get_global_setting('admin_refresh_token', '')
    if not encrypted:
        print("No admin refresh token in DB")
        return
    token = decrypt_token(encrypted)
    if not token:
        print("Failed to decrypt token")
        return
    print("Fetching access token...")
    resp = zoho_api.refresh_access_token(token)
    access_token = resp.get('access_token')
    if not access_token:
        print(f"Failed to get access token: {resp}")
        return
    print("Fetching modules...")
    modules_data = zoho_api.fetch_module_metadata(access_token)
    if 'modules' not in modules_data:
        print(f"No modules in response: {modules_data}")
        return
    
    print("\nCustom Modules Found:")
    for m in modules_data['modules']:
        # Print if it looks custom
        is_custom = m.get('generated_type') == 'custom' or 'CustomModule' in str(m)
        if is_custom:
            print(f"\nAPI Name: {m.get('api_name')}")
            print(f"Plural Label: {m.get('plural_label')}")
            print(f"Generated Type: {m.get('generated_type')}")
            for k, v in m.items():
                if isinstance(v, str) and 'CustomModule' in v:
                    print(f"  Found key '{k}' = '{v}'")

if __name__ == '__main__':
    main()
