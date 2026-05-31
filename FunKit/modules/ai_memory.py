import json

def get_memory(conn, key="global"):
    row = conn.execute("SELECT value FROM ai_memory WHERE key=?", (key,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}

def set_memory(conn, data: dict, key="global"):
    blob = json.dumps(data, ensure_ascii=False)
    conn.execute("INSERT OR REPLACE INTO ai_memory(key,value) VALUES(?,?)", (key, blob))
    conn.commit()
