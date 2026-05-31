import sqlite3
from modules.db_migrations import ensure_ai_memory_table

class DocumentStore:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
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
            self.conn.execute("ALTER TABLE documents ADD COLUMN content_type TEXT DEFAULT 'text/plain'")
            self.conn.commit()

    def create_table(self):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, title TEXT, body TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    def add_document(self, title, body):
        cur = self.conn.execute(
            "INSERT INTO documents (title, body) VALUES (?, ?)", 
            (title, body)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_document(self, doc_id: int, new_body: str):
        self.conn.execute(
            "UPDATE documents SET body = ? WHERE id = ?",
            (new_body, doc_id)
        )
        self.conn.commit()

    def append_to_document(self, doc_id: int, extra_text: str):
        row = self.get_document(doc_id)
        if not row:
            raise ValueError(f"No document with id {doc_id}")

        current_body = row["body"] if isinstance(row, dict) else row[2]
        if current_body is None:
            current_body = ""

        new_body = current_body + "\n" + extra_text
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
                desc = body[:60].replace("\n", " ").replace("\r", " ")
            result.append({"id": row["id"], "title": row["title"], "description": desc})
        return result

    def get_document(self, doc_id):
        cur = self.conn.execute("SELECT id, title, body FROM documents WHERE id=?", (doc_id,))
        return cur.fetchone()

    def delete_document(self, doc_id: int):
        self.conn.execute(
            "DELETE FROM documents WHERE id = ?",
            (doc_id,)
        )
        self.conn.commit()

    # AI Memory Methods
    def add_memory(self, role: str, content: str) -> int:
        """Add a new memory entry to the AI memory table"""
        cur = self.conn.execute(
            "INSERT INTO ai_memory (role, content) VALUES (?, ?)",
            (role, content)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_recent_memories(self, limit: int = 10, role: str = None) -> list:
        """
        Retrieve recent memories with optional role filtering
        Returns list of sqlite3.Row objects with id, role, content, timestamp
        """
        query = "SELECT * FROM ai_memory"
        params = []
        
        if role:
            query += " WHERE role = ?"
            params.append(role)
            
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cur = self.conn.execute(query, tuple(params))
        return cur.fetchall()

    def clear_memories(self):
        """Delete all entries from the AI memory table"""
        self.conn.execute("DELETE FROM ai_memory")
        self.conn.commit()

    def delete_memory(self, memory_id: int):
        """Delete a specific memory by its ID"""
        self.conn.execute(
            "DELETE FROM ai_memory WHERE id = ?",
            (memory_id,)
        )
        self.conn.commit()
