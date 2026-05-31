from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Any

from modules.db_migrations import ensure_ai_memory_table


DEFAULT_DB_PATH = Path("storage") / "documents.db"


class DocumentStore:
    def __init__(self, db_path: str | os.PathLike[str] = DEFAULT_DB_PATH):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_table()
        ensure_ai_memory_table(self.conn)
        self.ensure_content_type_column()

    def get_connection(self):
        return self.conn

    def ensure_content_type_column(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(documents)")
        cols = {row[1] for row in cur.fetchall()}
        if "content_type" not in cols:
            self.conn.execute(
                "ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text/plain'"
            )
            self.conn.commit()

    def create_table(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                title TEXT,
                body TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def add_document(self, title, body, content_type: str | None = None):
        cur = self.conn.execute(
            "INSERT INTO documents (title, body, content_type) VALUES (?, ?, ?)",
            (title, body, content_type or "text/plain"),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_document(self, doc_id: int, new_body: Any):
        self.conn.execute(
            "UPDATE documents SET body = ? WHERE id = ?",
            (new_body, doc_id),
        )
        self.conn.commit()

    def update_document_body(self, doc_id: int, new_body: Any):
        self.update_document(doc_id, new_body)

    def append_to_document(self, doc_id: int, extra_text: str):
        row = self.get_document(doc_id)
        if not row:
            raise ValueError(f"No document with id {doc_id}")

        current_body = row["body"]
        if current_body is None:
            current_body = ""
        if isinstance(current_body, bytes):
            current_body = current_body.decode("utf-8", errors="replace")

        new_body = str(current_body) + "\n" + extra_text
        self.update_document(doc_id, new_body)

    def get_document_index(self):
        cur = self.conn.execute(
            "SELECT id, title, body FROM documents ORDER BY id DESC"
        )
        result = []
        for row in cur.fetchall():
            body = row["body"]
            if body is None:
                body = ""
            if isinstance(body, bytes):
                desc = f"[{len(body)} bytes]"
            else:
                desc = str(body)[:60].replace("\n", " ").replace("\r", " ")
            result.append(
                {"id": row["id"], "title": row["title"], "description": desc}
            )
        return result

    def list_documents(self):
        cur = self.conn.execute(
            "SELECT id, title, body FROM documents ORDER BY id DESC"
        )
        docs = []
        for row in cur.fetchall():
            body = row["body"]
            if isinstance(body, bytes):
                summary = f"{row['title']} [{len(body)} bytes]"
            else:
                preview = str(body or "").replace("\n", " ").replace("\r", " ")[:60]
                summary = f"{row['title']}: {preview}" if preview else str(row["title"])
            docs.append((row["id"], summary))
        return docs

    def get_document(self, doc_id):
        cur = self.conn.execute(
            "SELECT id, title, body, created_at, content_type FROM documents WHERE id=?",
            (doc_id,),
        )
        return cur.fetchone()

    def get_document_text(self, doc_id: int) -> str:
        row = self.get_document(doc_id)
        if not row:
            raise ValueError(f"No document with id {doc_id}")
        body = row["body"]
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body or "")

    def has_title(self, title: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM documents WHERE title = ? LIMIT 1",
            (title,),
        )
        return cur.fetchone() is not None

    def import_csv(self, filename="import.csv"):
        path = Path(filename)
        if not path.exists():
            raise FileNotFoundError(f"{filename} not found.")

        with path.open("r", newline="", encoding="utf-8") as csvfile:
            sample = csvfile.read(1024)
            csvfile.seek(0)
            has_header = False
            try:
                has_header = csv.Sniffer().has_header(sample)
            except csv.Error:
                pass

            reader = csv.reader(csvfile)
            if has_header:
                next(reader, None)

            for row in reader:
                if len(row) >= 2 and row[0].strip():
                    self.add_document(row[0].strip(), row[1].strip() if row[1] else "")

    def export_csv(self, filename="export.csv"):
        cur = self.conn.execute("SELECT title, body FROM documents ORDER BY id")
        with Path(filename).open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["title", "body"])
            for title, body in cur.fetchall():
                if isinstance(body, bytes):
                    body = body.decode("utf-8", errors="replace")
                writer.writerow([title, body])

    def delete_document(self, doc_id: int):
        self.conn.execute(
            "DELETE FROM documents WHERE id = ?",
            (doc_id,),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
