# example_repo.py
from modules.TreeView import RepoProtocol, DocNode
import sqlite3

class SQLiteRepo(RepoProtocol):
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def get_doc(self, doc_id: int):
        r = self.conn.execute("SELECT id, title, parent_id, created_at FROM documents WHERE id=?", (doc_id,)).fetchone()
        return DocNode(r["id"], r["title"], r["parent_id"], r["created_at"]) if r else None

    def get_children(self, parent_id):
        if parent_id is None:
            sql = "SELECT id, title, parent_id, created_at FROM documents WHERE parent_id IS NULL ORDER BY id"
            rows = self.conn.execute(sql).fetchall()
        else:
            sql = "SELECT id, title, parent_id, created_at FROM documents WHERE parent_id=? ORDER BY id"
            rows = self.conn.execute(sql, (parent_id,)).fetchall()
        return [DocNode(r["id"], r["title"], r["parent_id"], r["created_at"]) for r in rows]

