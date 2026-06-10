import sys
import os
import json

# If running on AWS Production/Ubuntu, auto-load secrets environment file
env_path = '/etc/zohomap/app.env'
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, val = line.split('=', 1)
                    os.environ[key.strip()] = val.strip()

# Ensure parent directory is in path to import database.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database

def main():
    conn = database.get_db_connection()
    try:
        module = sys.argv[1] if len(sys.argv) > 1 else 'Accounts'
        print(f"Querying last 10 global records for module: {module}")
        
        rows = database.exec_query(conn, 
            "SELECT id, name, lat, lng, franchise_id, record_data FROM module_records WHERE user_id = ? AND module_name = ?", 
            ('__global__', module), fetchall=True)
            
        print(f"Found {len(rows)} global records in database for {module}.")
        
        records = []
        for r in rows:
            data = r['record_data']
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    pass
            
            mod_time = 'Unknown'
            if isinstance(data, dict):
                mod_time = data.get('Modified_Time') or data.get('Modified_Time1') or data.get('_modified_time') or 'Unknown'
                
            records.append({
                'id': r['id'],
                'name': r['name'],
                'lat': r['lat'],
                'lng': r['lng'],
                'franchise_id': r['franchise_id'],
                'modified_time': mod_time
            })
            
        try:
            records.sort(key=lambda x: str(x['modified_time']), reverse=True)
        except Exception:
            pass
            
        print("\nLast 10 records by Zoho Modified_Time:")
        for r in records[:10]:
            print(f"ID: {r['id']} | Name: {r['name']} | Lat: {r['lat']} | Lng: {r['lng']} | Franchise: {r['franchise_id']} | Modified: {r['modified_time']}")
            
    finally:
        conn.close()

if __name__ == '__main__':
    main()
