import sqlite3
import mimetypes, pathlib
from typing import Union, Optional

class DocumentStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.ensure_content_type_column()

    def ensure_content_type_column(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(documents)")
        cols = {row[1] for row in cur.fetchall()}
        if "content_type" not in cols:
            self.conn.execute("ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text/plain'")
            self.conn.commit()

    def add_document(self, title: str, body: Union[str, bytes], content_type: str = "text/plain") -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO documents (title, body, content_type) VALUES (?, ?, ?)",
            (title, body, content_type),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_document(self, doc_id: int, new_body: Union[str, bytes], content_type: Optional[str] = None):
        if content_type is None:
            self.conn.execute("UPDATE documents SET body=? WHERE id=?", (new_body, doc_id))
        else:
            self.conn.execute("UPDATE documents SET body=?, content_type=? WHERE id=?", (new_body, content_type, doc_id))
        self.conn.commit()

    def get_document(self, doc_id: int):
        row = self.conn.execute("SELECT id, title, body, content_type FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "title": row["title"], "body": row["body"], "content_type": row["content_type"]}

    def append_to_document(self, doc_id: int, extra_text: str):
        row = self.get_document(doc_id)
        if not row:
            raise ValueError(f"No document with id {doc_id}")
        body = row["body"] or ""
        if isinstance(body, bytes):
            raise ValueError("Cannot append text to binary document")
        if body and not body.endswith("\n"):
            body += "\n"
        self.update_document(doc_id, body + extra_text, content_type=row["content_type"] or "text/plain")

    def add_image_from_file(self, path: str, title: str = None) -> int:
        p = pathlib.Path(path)
        data = p.read_bytes()
        ctype, _ = mimetypes.guess_type(p.name)
        if not ctype or not ctype.startswith("image/"):
            raise ValueError("Not an image file")
        return self.add_document(title or p.stem, data, content_type=ctype)
