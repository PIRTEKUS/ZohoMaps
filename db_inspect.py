import sqlite3
import json

try:
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    
    output = []
    
    # 1. Schema version
    r = conn.execute("SELECT value FROM global_settings WHERE key = 'schema_version'").fetchone()
    schema_ver = r[0] if r else "None"
    output.append(f"Schema Version: {schema_ver}")
    
    # 2. Distinct franchise_id from module_records (if column exists)
    try:
        rows = conn.execute("SELECT DISTINCT franchise_id, COUNT(*) as cnt FROM module_records GROUP BY franchise_id").fetchall()
        output.append("\nDistinct franchise_id in module_records:")
        for r in rows:
            output.append(f"  ID: {r['franchise_id']} | Count: {r['cnt']}")
    except Exception as e:
        output.append(f"\nError querying module_records franchise_id: {e}")
        
    # 3. Check what columns exist in module_records
    try:
        cols = [col[1] for col in conn.execute("PRAGMA table_info(module_records)").fetchall()]
        output.append(f"\nmodule_records columns: {cols}")
    except Exception as e:
        output.append(f"\nError getting module_records columns: {e}")
        
    # 4. Read cached franchise debug info for any users
    try:
        rows = conn.execute("SELECT key, value FROM global_settings WHERE key LIKE 'franchise_ids_%'").fetchall()
        output.append("\nCached franchise_ids in global_settings:")
        for r in rows:
            val_str = r['value']
            try:
                val = json.loads(val_str)
                output.append(f"  Key: {r['key']} -> IDs: {val.get('ids')} | Names: {val.get('names')}")
            except Exception:
                output.append(f"  Key: {r['key']} -> Raw: {val_str[:200]}")
    except Exception as e:
        output.append(f"\nError querying global_settings for franchise_ids: {e}")

    with open('db_inspect.txt', 'w', encoding='utf-8') as f:
        f.write("\n".join(output))
    print("Done")
except Exception as e:
    with open('db_inspect.txt', 'w', encoding='utf-8') as f:
        f.write(f"Exception: {e}")
