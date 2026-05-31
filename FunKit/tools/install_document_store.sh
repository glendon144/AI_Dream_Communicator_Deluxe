#!/usr/bin/env bash
set -euo pipefail

TARGET="modules/document_store.py"
BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"

[[ -f "$TARGET" ]] && cp "$TARGET" "$BACKUP" && echo "📦 Backup: $BACKUP"
mkdir -p modules

cat > "$TARGET" <<'PY'
# modules/document_store.py
# Unified, stable DocumentStore for FunKit / PiKit forks
# - Provides add_document / new_document / create_document (shim)
# - Provides get_document / list_documents / update_document / delete_document
# - Provides export_document_to_html / permalink_for
# - Auto-creates SQLite schema at storage/documents-db.sqlite3

from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now() -> str:
    return datetime.utcnow().strftime(ISO)


class DocumentStore:
    """
    A minimal, sturdy SQLite-backed store with a stable API surface compatible
    with multiple historical forks.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        # Default location (compatible with prior conversations)
        storage_dir = Path("storage")
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Prefer a single SQLite file named "documents-db.sqlite3"
        # If your project expects a different name, symlink it or adjust here.
        self.db_path = Path(db_path) if db_path else storage_dir / "documents-db.sqlite3"

        # Export directory (for permalink/export helpers)
        self.export_dir = storage_dir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

        # Ensure schema
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
                content_type TEXT,      -- common forks store this separately
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # lightweight index for listings
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

        # Normalize metadata (and capture kwargs)
        md = dict(metadata or {})
        # Fold through well-known fields commonly passed by various forks
        content_type = kwargs.pop("content_type", md.get("content_type"))
        if content_type is not None:
            md.setdefault("content_type", content_type)

        # Keep the remaining kwargs in metadata to avoid breaking callers
        for k, v in list(kwargs.items()):
            # don't overwrite explicit keys set above
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

    # Historical alias seen in some forks
    def new_document(
        self,
        content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        return self.add_document(content, title=title, metadata=metadata, **kwargs)

    # Legacy compatibility shim
    def create_document(
        self,
        content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> int:
        """Legacy compatibility shim. Accepts extra kwargs like content_type, tags, etc."""
        # Try the modern APIs with kwargs (then retry without if strict)
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
        content:

