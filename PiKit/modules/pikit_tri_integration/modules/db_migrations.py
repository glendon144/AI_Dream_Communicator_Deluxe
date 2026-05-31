def ensure_ai_memory_table(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS ai_memory (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    conn.commit()
