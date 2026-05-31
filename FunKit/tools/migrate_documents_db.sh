#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${1:-storage/documents.db}"   # pass a custom path if needed
BACKUP="$DB_PATH.bak.$(date +%Y%m%d-%H%M%S)"

if [[ ! -f "$DB_PATH" ]]; then
  echo "❌ DB not found at $DB_PATH"
  exit 1
fi

cp "$DB_PATH" "$BACKUP"
echo "📦 Backup: $BACKUP"

python3 - <<PY
import sqlite3, sys, datetime, json

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def colnames(table):
    cur.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}

def has_index(name):
    cur.execute("PRAGMA index_list(documents)")
    return any(row[1] == name for row in cur.fetchall())

cols = colnames("documents")

# Add missing columns (non-destructive)
if "created_at" not in cols:
    cur.execute("ALTER TABLE documents ADD COLUMN created_at TEXT")
if "updated_at" not in cols:
    cur.execute("ALTER TABLE documents ADD COLUMN updated_at TEXT")
if "metadata" not in cols:
    cur.execute("ALTER TABLE documents ADD COLUMN metadata TEXT")
if "content_type" not in cols:
    cur.execute("ALTER TABLE documents ADD COLUMN content_type TEXT")

# Backfill timestamps & metadata for rows where they are NULL
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

# If created_at was missing, initialize to now
cur.execute("UPDATE documents SET created_at = ? WHERE created_at IS NULL", (now,))
# If updated_at was missing, initialize to created_at if present, else now
cur.execute("""
UPDATE documents
   SET updated_at = COALESCE(updated_at, created_at, ?)
 WHERE updated_at IS NULL
""", (now,))
# Ensure metadata is a JSON object (at least "{}")
cur.execute("""
UPDATE documents
   SET metadata = '{}'
 WHERE metadata IS NULL OR TRIM(metadata) = ''
""")

conn.commit()

# Create index if missing
if not has_index("idx_documents_updated"):
    try:
        cur.execute("CREATE INDEX idx_documents_updated ON documents(updated_at)")
        conn.commit()
    except Exception as e:
        # If some old SQLite blocks this silently, continue
        pass

print("✅ Migration complete.")
PY
"$DB_PATH"

echo "🎉 Done migrating $DB_PATH"

