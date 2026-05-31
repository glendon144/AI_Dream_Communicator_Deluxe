#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-storage/documents.db}"   # optional arg; defaults to storage/documents.db
[[ -f "$DB_PATH" ]] || { echo "❌ DB not found: $DB_PATH"; exit 1; }

BACKUP="$DB_PATH.bak.$(date +%Y%m%d-%H%M%S)"
cp "$DB_PATH" "$BACKUP"
echo "📦 Backup: $BACKUP"

# Export for the Python block
export DB_PATH

python3 - <<'PY'
import os, sqlite3, datetime, json

db_path = os.environ.get("DB_PATH", "storage/documents.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def colnames(table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}

def has_index(table, name):
    cur.execute(f"PRAGMA index_list({table})")
    return any((r[1] == name) for r in cur.fetchall())

# Ensure table exists (some very old forks used different bootstrap)
cur.execute("""
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT
)
""")
conn.commit()

cols = colnames("documents")

# Add missing columns non-destructively
adds = []
if "metadata"     not in cols: adds.append(("metadata",     "TEXT"))
if "content_type" not in cols: adds.append(("content_type", "TEXT"))
if "created_at"   not in cols: adds.append(("created_at",   "TEXT"))
if "updated_at"   not in cols: adds.append(("updated_at",   "TEXT"))

for name, typ in adds:
    cur.execute(f"ALTER TABLE documents ADD COLUMN {name} {typ}")
conn.commit()

# Backfill
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
cur.execute("UPDATE documents SET metadata = '{}' WHERE metadata IS NULL OR TRIM(metadata) = ''")
cur.execute("UPDATE documents SET created_at = COALESCE(created_at, ?)", (now,))
cur.execute("UPDATE documents SET updated_at = COALESCE(updated_at, created_at, ?)", (now,))
conn.commit()

# Index on updated_at (if column now exists)
if "updated_at" in colnames("documents") and not has_index("documents", "idx_documents_updated"):
    try:
        cur.execute("CREATE INDEX idx_documents_updated ON documents(updated_at)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

print("✅ Migration complete for", db_path)
PY

echo "🎉 Done migrating $DB_PATH"

