#!/usr/bin/env python3
import os
import sqlite3

DB_PATH = "storage/documents.db"

def get_file_size(path):
    return os.path.getsize(path) / (1024 * 1024)

def vacuum_database(path):
    print(f"🔍 Opening database: {path}")
    size_before = get_file_size(path)
    print(f"💾 Size before VACUUM: {size_before:.2f} MB")

    with sqlite3.connect(path) as conn:
        conn.execute("VACUUM;")
        conn.commit()

    size_after = get_file_size(path)
    print(f"✅ Size after VACUUM: {size_after:.2f} MB")
    print(f"💡 Saved: {size_before - size_after:.2f} MB")

if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        vacuum_database(DB_PATH)
    else:
        print(f"❌ Database not found at: {DB_PATH}")

