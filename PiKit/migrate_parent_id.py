#!/usr/bin/env python3
import sqlite3
import os

DB_PATH = "./storage/documents.db"

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cursor.fetchall()]
    return column in cols

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check if parent_id column exists
    if not column_exists(cur, "documents", "parent_id"):
        print("🔧 Adding parent_id column to documents table...")
        cur.execute("ALTER TABLE documents ADD COLUMN parent_id INTEGER;")
        conn.commit()
        print("✅ Column added.")
    else:
        print("ℹ️ parent_id column already exists. No changes made.")

    # Show schema after migration
    print("\n📜 Updated table schema:")
    cur.execute("PRAGMA table_info(documents);")
    for row in cur.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    migrate()

