#!/usr/bin/env bash
set -euo pipefail

TARGET="modules/document_store.py"
BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"

mkdir -p modules storage/exports
if [[ -f "$TARGET" ]]; then
  cp "$TARGET" "$BACKUP"
  echo "📦 Backup: $BACKUP"
fi

python3 - "$TARGET" <<'PY'
import json, sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"

def _now() -> str:
    return datetime.utcnow().strftime(ISO)

FILE_CONTENT = r'''
# modules/document_store.py
# Unified, stable DocumentStore for FunKit / PiKit forks

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now() -> str:
    return datetime.utcnow().strftime(ISO)


class DocumentStore:
    """
    A minimal, sturdy SQLite-backed store with a stable API surface compatible
    with multiple historical forks.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        storage_dir = Path("storage")
        storage_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = Path(db_path) if db_path else storage_dir / "documents-db.sqlite3"

        self.export_dir = storage_dir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    # -------- Schema --------
    def _ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                metadata TEXT,          -- JSON blob
                content_type TEXT,      -- optional top-level convenience
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at)")
        self._conn.commit()

    # -------- Creation --------
    def add_document(
        self,
        content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        """
        Primary creation method. Accepts extra kwargs; we fold known ones into columns/metadata.
        """
        created = _now()
        updated = created

        md = dict(metadata or {})

        # Common callers pass content_type either as kwarg or in metadata
        content_type = kwargs.pop("content_type", md.get("content_type"))
        if content_type is not None:
            md.setdefault("content_type", content_type)

        # Preserve any remaining kwargs inside metadata so callers never break
        for k, v in list(kwargs.items()):
            if k not in md:
                md[k] = v

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO documents (title, content, metadata, content_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                content,
                json.dumps(md, ensure_ascii=False),
                content_type,
                created,
                updated,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def new_document(
        self,
        content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        """Historical alias used by some forks."""
        return self.add_document(content, title=title, metadata=metadata, **kwargs)

    def create_document(
        self,
        content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        """Legacy compatibility shim. Accepts extra kwargs like content_type, tags, etc."""
        try:
            return self.add_document(content, title=title, metadata=metadata, **kwargs)
        except TypeError:
            return self.add_document(content, title=title, metadata=metadata)

    # -------- Reads --------
    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_documents(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        cur = self._conn.cursor()
        q = "SELECT * FROM documents ORDER BY updated_at DESC"
        if limit is not None:
            q += " LIMIT ?"
            cur.execute(q, (limit,))
        else:
            cur.execute(q)
        return [self._row_to_dict(r) for r in cur.fetchall()]

    # -------- Update / Delete --------
    def update_document(
        self,
        doc_id: int,
        *,
        title: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> bool:
        """
        Partial update. Extra kwargs are folded into metadata (non-destructively).
        """
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        if not row:
            return False

        existing = self._row_to_dict(row)

        new_title = title if title is not None else existing["title"]
        new_content = content if content is not None else existing["content"]

        md = dict(existing.get("metadata") or {})
        if metadata:
            md.update(metadata)

        for k, v in kwargs.items():
            md[k] = v

        content_type = md.get("content_type", existing.get("content_type"))

        updated = _now()
        cur.execute(
            """
            UPDATE documents
               SET title = ?, content = ?, metadata = ?, content_type = ?, updated_at = ?
             WHERE id = ?
            """,
            (new_title, new_content, json.dumps(md, ensure_ascii=False), content_type, updated, doc_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_document(self, doc_id: int) -> bool:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # -------- Export / Permalink helpers --------
    def export_document_to_html(self, doc_id: int) -> str:
        """
        Export a single document to a simple HTML file and return the file path.
        """
        doc = self.get_document(doc_id)
        if not doc:
            raise KeyError(f"No document with id={doc_id}")

        title = doc.get("title") or f"Document {doc_id}"
        content = doc.get("content") or ""

        html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{self._escape_html(title)}</title>
  <meta name="generator" content="DocumentStore export">
</head>
<body>
  <article>
    <h1>{self._escape_html(title)}</h1>
    <pre style="white-space: pre-wrap;">{self._escape_html(content)}</pre>
  </article>
</body>
</html>
"""
        out_path = self.export_dir / f"doc_{doc_id}.html"
        out_path.write_text(html, encoding="utf-8")
        return str(out_path)

    def permalink_for(self, doc_id: int) -> str:
        path = self.export_document_to_html(doc_id)
        return f"file://{str(Path(path).absolute())}"

    # -------- Utilities --------
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        md = {}
        if row["metadata"]:
            try:
                md = json.loads(row["metadata"])
            except Exception:
                md = {"_raw_metadata": row["metadata"]}

        return {
            "id": int(row["id"]),
            "title": row["title"],
            "content": row["content"],
            "metadata": md,
            "content_type": row["content_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _escape_html(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )


def get_store(db_path: Optional[str] = None) -> DocumentStore:
    return DocumentStore(db_path=db_path)
'''

target = Path(__import__('sys').argv[1])
target.write_text(FILE_CONTENT, encoding="utf-8")
print(f"📝 Wrote {target}")
PY

python3 -m py_compile "$TARGET"
echo "✅ Installed $TARGET"

