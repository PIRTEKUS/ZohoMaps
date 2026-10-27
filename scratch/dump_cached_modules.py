import json
from database import get_db_connection, exec_query

def main():
    conn = get_db_connection()
    rows = exec_query(conn, "SELECT key, value FROM global_settings", fetchall=True)
    conn.close()
    
    for row in rows:
        key = row['key']
        val = row['value']
        print(f"Key: {key}")
        if key == 'cached_modules' or key.startswith('cached_fields'):
            try:
                data = json.loads(val)
                print(f"Value (parsed JSON, len {len(data)}):")
                print(json.dumps(data, indent=2)[:1000] + "\n...")
            except Exception as e:
                print(f"Value: {val[:200]} (Error parsing: {e})")
        else:
            print(f"Value: {val[:200]}")
        print("-" * 50)

if __name__ == '__main__':
    main()
