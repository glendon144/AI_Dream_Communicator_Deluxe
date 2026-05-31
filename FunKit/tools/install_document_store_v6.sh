#!/usr/bin/env bash
set -euo pipefail

TARGET="modules/document_store.py"
BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"

mkdir -p modules storage/exports
[[ -f "$TARGET" ]] && cp "$TARGET" "$BACKUP" && echo "📦 Backup: $BACKUP"

python3 - "$TARGET" <<'PY'
from pathlib import Path
FILE_CONTENT = r'''
# modules/document_store.py
# Unified, stable DocumentStore for FunKit / PiKit forks
# v6:
#   - get_document_index(): description is first 60 chars of content (legacy behavior)
#   - Provide 'body' alias (doc["body"] == doc["content"]) and body helpers

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now() -> str:
    return datetime.now(UTC).strftime(ISO)


class DocumentStore:
    """
    SQLite-backed store compatible with multiple historical forks.
    - Auto-creates table
    - Auto-adds missing columns
    - Legacy-friendly API surface (aliases + field shims)
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
        # Base table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT
            )
            """
        )
        self._conn.commit()

        # Add missing columns on legacy DBs
        cur.execute("PRAGMA table_info(documents)")
        have = {row[1] for row in cur.fetchall()}
        adds = []
        if "metadata" not in have:     adds.append(("metadata",     "TEXT"))
        if "content_type" not in have: adds.append(("content_type", "TEXT"))
        if "created_at" not in have:   adds.append(("created_at",   "TEXT"))
        if "updated_at" not in have:   adds.append(("updated_at",   "TEXT"))
        if "content" not in have:      adds.append(("content",      "TEXT"))
        if "title" not in have:        adds.append(("title",        "TEXT"))
        for name, typ in adds:
            cur.execute(f"ALTER TABLE documents ADD COLUMN {name} {typ}")
        self._conn.commit()

        # Backfill sane defaults
        now = _now()
        cur.execute("UPDATE documents SET metadata = '{}' WHERE metadata IS NULL OR TRIM(COALESCE(metadata,'')) = ''")
        cur.execute("UPDATE documents SET created_at = COALESCE(created_at, ?)", (now,))
        cur.execute("UPDATE documents SET updated_at = COALESCE(updated_at, created_at, ?)", (now,))
        cur.execute("UPDATE documents SET title   = COALESCE(title, '')")
        cur.execute("UPDATE documents SET content = COALESCE(content, '')")
        self._conn.commit()

        # Index for listings
        cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_updated ON documents(updated_at)")
        self._conn.commit()

    # -------- Creation --------
    def add_document(self, content: str, title: Optional[str] = None,
                     metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
        created = _now()
        updated = created
        md = dict(metadata or {})
        content_type = kwargs.pop("content_type", md.get("content_type"))
        if content_type is not None:
            md.setdefault("content_type", content_type)
        for k, v in list(kwargs.items()):
            if k not in md:
                md[k] = v
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO documents (title, content, metadata, content_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, content, json.dumps(md, ensure_ascii=False), content_type, created, updated),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    # Aliases
    def new_document(self, content: str, title: Optional[str] = None,
                     metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
        return self.add_document(content, title=title, metadata=metadata, **kwargs)

    def insert_document(self, content: str, title: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
        return self.add_document(content, title=title, metadata=metadata, **kwargs)

    def create_document(self, content: str, title: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
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

    # Sidebar index (GUI expects dicts with id/title/description)
    def get_document_index(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        docs = self.list_documents(limit)
        out: List[Dict[str, Any]] = []
        for d in docs:
            title = (d.get("title") or "").strip()
            if not title:
                c0 = (d.get("content") or "").strip()
                first = c0.splitlines()[0] if c0 else ""
                title = first[:80] if first else f"Document {d['id']}"
            # legacy: first 60 characters of content only (no newlines)
            c = (d.get("content") or "").replace("\n", " ").strip()
            desc = c[:60]
            out.append({"id": d["id"], "title": title, "description": desc})
        return out

    # Back-compat (tuples)
    def get_document_index_tuples(self, limit: Optional[int] = None) -> List[Tuple[int, str]]:
        return [(d["id"], d["title"]) for d in self.get_document_index(limit)]

    # Convenience
    def all_documents(self) -> List[Dict[str, Any]]:
        return self.list_documents()

    def get_documents(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.list_documents(limit=limit)

    # -------- Update / Delete --------
    def update_document(self, doc_id: int, *, title: Optional[str] = None,
                        content: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                        **kwargs: Any) -> bool:
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
    @staticmethod
    def _row_get(row: sqlite3.Row, key: str, default=None):
        return row[key] if key in row.keys() else default

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        meta_raw = self._row_get(row, "metadata", None)
        md = {}
        if meta_raw:
            try:
                md = json.loads(meta_raw)
            except Exception:
                md = {"_raw_metadata": meta_raw}

        d = {
            "id": int(self._row_get(row, "id", 0) or 0),
            "title": self._row_get(row, "title", "") or "",
            "content": self._row_get(row, "content", "") or "",
            "metadata": md,
            "content_type": self._row_get(row, "content_type", None),
            "created_at": self._row_get(row, "created_at", _now()),
            "updated_at": self._row_get(row, "updated_at", _now()),
        }
        # Field aliases for very old callers
        d["created"] = d["created_at"]
        d["updated"] = d["updated_at"]
        # Important: body alias for GUIs that render doc["body"]
        d["body"] = d["content"]
        return d

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
Path(__import__('sys').argv[1]).write_text(FILE_CONTENT, encoding="utf-8")
print("📝 Wrote", __import__('sys').argv[1])
PY

python3 -m py_compile "$TARGET"
echo "✅ Installed $TARGET"

