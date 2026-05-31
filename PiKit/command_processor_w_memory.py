# PiKit Command Processor (updated with memory preamble + truncation)
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Tuple

from modules.logger import Logger
from modules.document_store import DocumentStore
from modules.directory_import import import_text_files_from_directory
from modules.ai_memory import get_memory, set_memory
from modules.text_sanitizer import sanitize_ai_reply

# Try to import a renderer for binary-as-text; provide a fallback shim if unavailable.
try:
    from modules.renderer import render_binary_as_text  # type: ignore
except Exception:  # pragma: no cover
    try:
        from modules.hypertext_parser import render_binary_as_text  # type: ignore
    except Exception:  # pragma: no cover
        def render_binary_as_text(data_or_path: Any, title: str = "Document") -> str:
            try:
                if isinstance(data_or_path, (bytes, bytearray)):
                    return data_or_path.decode("utf-8", errors="replace")
                if isinstance(data_or_path, str) and os.path.exists(data_or_path):
                    with open(data_or_path, "rb") as f:
                        raw = f.read()
                    return raw.decode("utf-8", errors="replace")
            except Exception:
                pass
            return str(data_or_path)


def _normalize_row(row: Any) -> Tuple[Any, str, Any]:
    """Normalize a document row to (id, title, body).
    Supports sqlite3.Row (mapping-like), dict, and sequence (tuple/list).
    """
    # sqlite3.Row behaves like a mapping and supports .keys() and index by column name
    try:
        if hasattr(row, "keys"):
            keys = set(row.keys())
            did = row["id"] if "id" in keys else None
            title = row["title"] if "title" in keys else "Document"
            body = row["body"] if "body" in keys else ""
            return did, (title or "Document"), body
    except Exception:
        pass

    # Dict path
    if isinstance(row, dict):
        return row.get("id"), (row.get("title") or "Document"), row.get("body")

    # Sequence path (tuple/list/sqlite3.Row via index access)
    try:
        if not isinstance(row, (str, bytes, bytearray)) and hasattr(row, "__getitem__"):
            did = row[0] if len(row) > 0 else None
            title = row[1] if len(row) > 1 else "Document"
            body = row[2] if len(row) > 2 else ""
            return did, (title or "Document"), body
    except Exception:
        pass

    # Fallback: treat entire row as body
    return None, "Document", row


class CommandProcessor:
    def __init__(self, store: DocumentStore, ai_interface, logger: Logger | None = None):
        self.doc_store = store
        self.ai = ai_interface
        self.logger = logger if logger else Logger()

    # --------------- Memory helpers ---------------

    def _get_conn(self):
        """Return the SQLite connection from the document store, if available."""
        return getattr(self.doc_store, "conn", None)

    def _build_memory_preamble(self, mem: dict, current_doc_id: int | None = None) -> str:
        """Construct a small instruction block from memory to steer the model."""
        if not isinstance(mem, dict):
            return ""
        persona = mem.get("persona")
        style = mem.get("style")
        rules = mem.get("rules", [])
        parts: list[str] = []
        if persona:
            parts.append(f"Persona: {persona}")
        if style:
            parts.append(f"Style: {style}")
        if rules:
            parts.append("Rules: " + "; ".join(rules))
        return "\n".join(parts).strip()

    def _update_memory_breadcrumbs(self, prompt: str) -> None:
        """Record last-used time and a short rolling log of prompts."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            mem = get_memory(conn, key="global")
            if not isinstance(mem, dict):
                mem = {}
            mem.setdefault("recent_prompts", [])
            mem["recent_prompts"] = (mem["recent_prompts"] + [prompt])[-20:]
            mem["last_used"] = int(time.time())
            set_memory(conn, mem, key="global")
        except Exception as e:
            # Non-fatal; keep the AI flow working even if memory write fails
            self.logger.info(f"Non-fatal: failed to update ai_memory: {e}")

    # --------------- Public API ---------------

    def set_api_key(self, api_key: str) -> None:
        try:
            self.ai.set_api_key(api_key)
            self.logger.info("API key successfully set in AI interface")
        except Exception as e:
            self.logger.error(f"Failed to set API key: {e}")

    def get_context_menu_actions(self) -> dict:
        return {
            "Import CSV": self.doc_store.import_csv,
            "Export CSV": self.doc_store.export_csv,
        }

    def ask_question(self, prompt: str) -> str | None:
        """Send a standalone prompt to AI, applying memory preamble and truncation."""
        try:
            conn = self._get_conn()
            mem = get_memory(conn, key="global") if conn else {}
            preamble = self._build_memory_preamble(mem)
            full_prompt = (preamble + "\n\n" + prompt) if preamble else prompt

            self.logger.info(f"Sending standalone prompt to AI: {full_prompt}")
            response = self.ai.query(full_prompt)
            response = sanitize_ai_reply(response)
            self.logger.info("AI response received successfully")
            self._update_memory_breadcrumbs(prompt)
            return response
        except Exception as e:
            self.logger.error(f"AI query failed: {e}")
            return None

    def query_ai(
        self,
        selected_text: str,
        current_doc_id: int,
        on_success,
        on_link_created,
        prefix: str | None = None,
        sel_start: int | None = None,
        sel_end: int | None = None,
    ) -> None:
        """
        Send the selection to AI, create a new doc with the response, and optionally embed
        a green link back into the source doc (text bodies only). Also applies memory preamble
        and truncates likely-incomplete sentences.
        """
        # Compose the base prompt
        base_prompt = f"{prefix} {selected_text}" if prefix else f"Please expand on this: {selected_text}"

        # Memory preamble
        conn = self._get_conn()
        mem = get_memory(conn, key="global") if conn else {}
        preamble = self._build_memory_preamble(mem, current_doc_id=current_doc_id)
        prompt = (preamble + "\n\n" + base_prompt) if preamble else base_prompt

        self.logger.info(f"Sending prompt: {prompt}")

        # Call AI
        try:
            reply = self.ai.query(prompt)
            reply = sanitize_ai_reply(reply)
        except Exception as e:
            self.logger.error(f"AI query failed: {e}")
            return

        self.logger.info("AI query successful")

        # Create the AI response document
        new_doc_id = self.doc_store.add_document("AI Response", reply)
        self.logger.info(f"Created new document {new_doc_id}")

        # Try to embed a green link in the original text document
        try:
            original = self.doc_store.get_document(current_doc_id)
        except Exception as e:
            original = None
            self.logger.error(f"Failed to load original doc {current_doc_id}: {e}")

        if original is not None:
            try:
                _, _title, body = _normalize_row(original)
            except Exception:
                body = ""

            if isinstance(body, str) and selected_text:
                link_md = f"[{selected_text}](doc:{new_doc_id})"
                updated: str | None = None

                # If explicit offsets are provided and valid, use them
                if (
                    isinstance(sel_start, int)
                    and isinstance(sel_end, int)
                    and 0 <= sel_start < sel_end <= len(body)
                ):
                    updated = body[:sel_start] + link_md + body[sel_end:]
                    self.logger.info(f"Embedded link at offsets {sel_start}-{sel_end}")
                else:
                    # Fallback: first occurrence replacement
                    if selected_text in body:
                        updated = body.replace(selected_text, link_md, 1)
                        self.logger.info("Embedded link by substring replace")
                    else:
                        self.logger.info("Selected text not found; original unchanged")

                if updated is not None and updated != body:
                    try:
                        if hasattr(self.doc_store, "update_document_body"):
                            self.doc_store.update_document_body(current_doc_id, updated)
                        else:
                            # Some stores expose a generic update_document(id, body)
                            self.doc_store.update_document(current_doc_id, updated)  # type: ignore
                    except Exception as e:
                        self.logger.error(f"Failed updating original doc {current_doc_id}: {e}")
            else:
                # Skip binary or missing bodies
                if isinstance(body, (bytes, bytearray)):
                    self.logger.info("Original doc is binary; skipping in-place link embed.")
        else:
            self.logger.error(f"Original document {current_doc_id} not found")

        # Update memory breadcrumbs (non-fatal on error)
        try:
            self._update_memory_breadcrumbs(base_prompt)
        except Exception:
            pass

        # Fire UI callbacks
        try:
            on_link_created(selected_text)
        except Exception as e:
            self.logger.info(f"on_link_created callback failed (non-fatal): {e}")
        try:
            on_success(new_doc_id)
        except Exception as e:
            self.logger.info(f"on_success callback failed (non-fatal): {e}")

    # --------------- External file operations ---------------

    def import_document_from_path(self, path: str) -> int:
        """Import a file from *path* and return new document ID."""
        p = Path(path)
        title = p.stem
        try:
            text = p.read_text(encoding="utf-8")
            return self.doc_store.add_document(title, text)
        except UnicodeDecodeError:
            data = p.read_bytes()  # store as SQLite BLOB
            return self.doc_store.add_document(title, data)

    def export_document_to_path(self, doc_id: int, path: str) -> None:
        """Export document *doc_id* to filesystem path."""
        row = self.doc_store.get_document(doc_id)

        if hasattr(row, "keys"):  # sqlite3.Row with mapping behavior
            body = row["body"] if row else ""
        elif isinstance(row, dict):
            body = row.get("body")
        else:
            body = row[2] if row and len(row) > 2 else ""

        p = Path(path)
        if isinstance(body, (bytes, bytearray)):
            p.write_bytes(bytes(body))
        else:
            p.write_text("" if body is None else str(body), encoding="utf-8")

    # --------------- Render helpers ---------------

    def get_strings_content(self, doc_id: int) -> str:
        """Return a text rendering of the document suitable for display/export."""
        try:
            row = self.doc_store.get_document(doc_id)
        except Exception:
            row = None

        if not row:
            return "[ERROR] Document not found."

        _id, title, body = _normalize_row(row)

        # If body looks like a filesystem path and exists, prefer that
        if isinstance(body, str) and os.path.exists(body):
            try:
                return render_binary_as_text(body, title)
            except Exception:
                pass

        # If it's bytes/bytearray, convert via renderer
        if isinstance(body, (bytes, bytearray)):
            return render_binary_as_text(body, title)

        # Else, return text as-is
        return str(body or "")

    # --------------- Bulk imports ---------------

    def import_opml_from_path(self, path: str) -> int:
        """Import an OPML/XML file from *path* and return new document ID."""
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        title = Path(path).stem
        return self.doc_store.add_document(title, content)

    def import_directory(self, directory: str) -> None:
        """Bulk-import text files from a directory."""
        import_text_files_from_directory(self.doc_store, directory)
