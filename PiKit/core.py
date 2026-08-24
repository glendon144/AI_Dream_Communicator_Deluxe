"""PiKitCore — GUI-agnostic application core for PiKit.

Owns the non-visual application lifecycle and business objects that the Tk
GUI (and a future Qt6 pane) render as views:

* document store, AI interface, command processor
* Dream processor + Dream enable/disable state
* handoff/inbox consumption and document import from handoff packets
* status reporting through a callback rather than direct Tk calls

The core is scheduler-neutral: it imports no tkinter/Qt and never calls
``app.after``/``QTimer``.  Views decide how one-shot methods such as
``consume_inbox_once()`` are scheduled (Tk ``after`` today, ``QTimer`` later).

Paths are explicit and default to locations under the product root, so
correctness does not depend on the process working directory.
"""

from __future__ import annotations

import queue
import socket
import threading
from pathlib import Path
from typing import Any, Callable

# Dual-mode imports: standalone ``python main.py`` resolves the top-level
# ``modules`` package (PiKit dir on sys.path); in-process embedding imports
# this module as ``PiKit.core``, where the package-relative forms are used.
try:
    from modules.command_processor import CommandProcessor
    from modules.document_store import DocumentStore
    from modules.dream import DreamProcessor
except ImportError:
    from .modules.command_processor import CommandProcessor
    from .modules.document_store import DocumentStore
    from .modules.dream import DreamProcessor

try:
    from dream_capture_inbox import (
        import_handoff_payload as _import_packet,
        process_inbox_once as _process_inbox_once,
    )
except ImportError:
    from .dream_capture_inbox import (
        import_handoff_payload as _import_packet,
        process_inbox_once as _process_inbox_once,
    )


def _null_status(message: str) -> None:
    pass


class _CallbackStatus:
    """Duck-typed ``status`` object with ``.set()`` for inbox view hooks."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def set(self, message: str) -> None:
        self._callback(message)


class _CoreInboxView:
    """Duck-typed view bridge: routes inbox notifications to core callbacks."""

    def __init__(
        self, core: "PiKitCore", on_imported: Callable[[int], None] | None
    ) -> None:
        self._core = core
        self._on_imported = on_imported

    def _refresh_index(self) -> None:
        # The core has no document index; the view refreshes via on_imported.
        pass

    def _open_doc_id(self, doc_id: int) -> None:
        if self._on_imported is not None:
            self._on_imported(doc_id)

    @property
    def status(self) -> _CallbackStatus:
        return _CallbackStatus(self._core.report_status)


class PiKitCore:
    """Application core for PiKit (business objects + lifecycle)."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        db_path: Path | str | None = None,
        dreams_db_path: Path | str | None = None,
        inbox_dir: Path | str | None = None,
        status: Callable[[str], None] | None = None,
        ai_interface: Any | None = None,
        doc_store: DocumentStore | None = None,
        processor: CommandProcessor | None = None,
    ):
        # Explicit paths (default under the product root, not the CWD).
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent
        self.storage_dir = self.root / "storage"
        self.db_path = (
            Path(db_path) if db_path is not None else self.storage_dir / "documents.db"
        )
        self.dreams_db_path = (
            Path(dreams_db_path)
            if dreams_db_path is not None
            else self.storage_dir / "dreams.db"
        )
        self.inbox_dir = (
            Path(inbox_dir) if inbox_dir is not None else self.storage_dir / "handoffs"
        )
        self.status_callback: Callable[[str], None] = (
            status if status is not None else _null_status
        )

        # Business objects (mirrors what main.py previously assembled).
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.doc_store = (
            doc_store if doc_store is not None else DocumentStore(str(self.db_path))
        )
        self.ai = ai_interface if ai_interface is not None else self._build_ai()
        self.processor = (
            processor
            if processor is not None
            else CommandProcessor(self.doc_store, self.ai)
        )

        # Dream state (owned here; the view renders buttons from it).
        self.dream_enabled = False
        self.current_doc_id: int | None = None
        self.dream_processor = self._build_dream_processor()
        self.dream_processor.start()
        self.dream_processor.authorize(False)
        if hasattr(self.processor, "set_dream_handler"):
            self.processor.set_dream_handler(self._on_dream_event)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ai() -> Any:
        # Lazily imported so this module stays importable without the
        # optional `openai` package (modules.ai_interface imports it at the
        # module level).
        try:
            from modules.ai_interface import AIInterface
        except ImportError:
            from .modules.ai_interface import AIInterface

        return AIInterface()

    def _build_dream_processor(self) -> DreamProcessor:
        self.dreams_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dreams_db_path.touch(exist_ok=True)
        # Defensive constructor fallbacks mirror the Tk GUI's original setup.
        for args, kwargs in (
            ((str(self.dreams_db_path),), {"main_db_reader": self._dream_main_db_reader}),
            ((str(self.dreams_db_path),), {}),
        ):
            try:
                return DreamProcessor(*args, **kwargs)
            except TypeError:
                continue
        raise RuntimeError("Dream processor is unavailable.")

    def _dream_main_db_reader(self) -> str:
        """Recent document titles for the Dream capsule's main-DB context hint."""
        try:
            rows = self.doc_store.get_document_index() or []
        except Exception:
            return ""
        titles: list[str] = []
        for row in rows[:8]:
            title = ""
            if isinstance(row, dict):
                title = row.get("title")
            elif row is not None and len(row) > 1:
                title = row[1]
            if title:
                titles.append(str(title))
        return "Recent documents: " + ", ".join(titles) if titles else ""

    # ------------------------------------------------------------------
    # Dream mode
    # ------------------------------------------------------------------

    def _on_dream_event(self, event_type: str, content: str, **metadata) -> None:
        self.record_dream_event(event_type, content, metadata or None)

    def record_dream_event(
        self,
        event_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        source_doc_id: int | None = None,
    ) -> None:
        """Feed one session event into the Dream processor."""
        if not self.dream_processor:
            return
        metadata = dict(metadata or {})
        if source_doc_id is None:
            source_doc_id = metadata.get("current_doc_id", self.current_doc_id)
        self.dream_processor.add_event(
            event_type=event_type,
            content_snippet=str(content),
            source_doc_id=source_doc_id,
            metadata=metadata,
        )

    def set_current_doc_id(self, doc_id: int | None) -> None:
        """Track the view's active document for Dream event attribution."""
        self.current_doc_id = doc_id

    def set_dream_enabled(self, enabled: bool) -> None:
        """Authorize idle Dream processing; state is owned by the core."""
        self.dream_enabled = bool(enabled)
        if self.dream_processor and hasattr(self.dream_processor, "authorize"):
            try:
                self.dream_processor.authorize(self.dream_enabled)
            except Exception:
                pass

    def run_dream_pass(self) -> str:
        """Run a Dream pass now and return the session capsule text."""
        if not self.dream_processor:
            raise RuntimeError("Dream processor is unavailable.")
        if hasattr(self.dream_processor, "force_dream_pass"):
            return str(self.dream_processor.force_dream_pass())
        if hasattr(self.dream_processor, "process_tick"):
            self.dream_processor.process_tick()
            return str(self.dream_processor.get_latest_capsule() or "Dream pass completed.")
        return str(self.dream_processor.get_latest_capsule() or "Dream pass completed.")

    # ------------------------------------------------------------------
    # Handoff / inbox
    # ------------------------------------------------------------------

    def import_handoff_payload(self, payload: dict[str, Any]) -> int:
        """Import a handoff packet (same schema as the file inbox)."""
        return _import_packet(payload, self.processor)

    def process_handoff_file(
        self, path: Path, on_imported: Callable[[int], None] | None = None
    ) -> int:
        """Import one inbox file; ``on_imported`` is the view's reveal hook."""
        try:
            from dream_capture_inbox import process_handoff_file as _process_file
        except ImportError:
            from .dream_capture_inbox import process_handoff_file as _process_file

        return _process_file(path, self.processor, _CoreInboxView(self, on_imported))

    def consume_inbox_once(
        self, on_imported: Callable[[int], None] | None = None
    ) -> list[int]:
        """Claim and import every queued handoff exactly once.

        Atomic claiming is provided by the rename-based claim in
        ``dream_capture_inbox.process_inbox_once``; a packet can never be
        imported twice, even with multiple consumers.
        """
        return _process_inbox_once(
            self.inbox_dir, self.processor, _CoreInboxView(self, on_imported)
        )

    # ------------------------------------------------------------------
    # Export / save-as-text
    # ------------------------------------------------------------------

    def document_to_plain_text(self, doc_id: int) -> tuple[str, str]:
        """Return ``(title, plain_text)`` for a document.

        Composes the GUI-free text-extraction helpers from the save-as-text
        plugin (OPML flattening, binary decode) so the Qt pane only needs a
        file dialog and a write.
        """
        doc = self.doc_store.get_document(doc_id)
        if not doc:
            raise ValueError(f"Document {doc_id} not found")
        try:
            from modules.save_as_text_plugin_v3 import (
                _doc_tuple,
                _flatten_opml_to_text,
                _is_opml_text,
            )
        except ImportError:
            from .modules.save_as_text_plugin_v3 import (
                _doc_tuple,
                _flatten_opml_to_text,
                _is_opml_text,
            )
        _doc_id, title, body = _doc_tuple(doc)
        if isinstance(body, (bytes, bytearray)):
            body = bytes(body).decode("utf-8", errors="replace")
        text = str(body or "").strip()
        if _is_opml_text(text):
            text = _flatten_opml_to_text(text)
        return str(title or "Document"), text

    def export_document_to_path(self, doc_id: int, path: Path | str) -> None:
        """Export the raw document body to a filesystem path (business logic)."""
        self.processor.export_document_to_path(doc_id, str(path))

    # ------------------------------------------------------------------
    # OPML actions (business conversions via the GUI-free aopmlengine)
    # ------------------------------------------------------------------

    @staticmethod
    def _aopmlengine():
        try:
            from modules import aopmlengine
        except ImportError:
            from .modules import aopmlengine
        return aopmlengine

    def convert_document_to_opml(self, doc_id: int) -> int:
        """Convert a document body to OPML and store it as a new document."""
        doc = self.doc_store.get_document(doc_id)
        if not doc:
            raise ValueError(f"Document {doc_id} not found")
        title = str(doc["title"] or "Document")
        body = doc["body"]
        xml = self._aopmlengine().convert_payload_to_opml(title, body)
        return int(self.doc_store.add_document(f"{title} (OPML)", xml))

    def batch_convert_documents_to_opml(self, doc_ids: list[int]) -> tuple[int, int]:
        """Convert each document id to OPML; return (converted, failed)."""
        converted = 0
        failed = 0
        for doc_id in doc_ids:
            try:
                self.convert_document_to_opml(int(doc_id))
                converted += 1
            except Exception:
                failed += 1
        return converted, failed

    def import_url_as_opml(self, url: str, timeout: int = 25) -> int:
        """Fetch a URL, convert its content to OPML, and store a new document."""
        import urllib.request

        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        xml = self._aopmlengine().convert_payload_to_opml(url, data)
        return int(self.doc_store.add_document(f"{url} (OPML)", xml))

    def crawl_opml(self, start: str, max_depth: int = 2) -> list[int]:
        """Crawl an OPML seed (URL or path) and import linked OPML documents."""
        return list(self.processor.crawl_opml_and_import(start, max_depth=max_depth))

    # ------------------------------------------------------------------
    # Document transfer listener (socket handling stays out of the UI loop)
    # ------------------------------------------------------------------

    def _document_transfer(self):
        try:
            from modules import document_transfer
        except ImportError:
            from .modules import document_transfer
        return document_transfer

    def start_transfer_listener(
        self,
        on_incoming: Callable[[dict[str, Any], "queue.Queue"], None] | None = None,
        port: int | None = None,
    ) -> int | None:
        """Start the incoming-document socket listener on a daemon thread.

        ``on_incoming(invite, response_queue)`` is invoked on the listener
        thread for each invitation; the view marshals the prompt to its UI
        thread and puts the JSON response into ``response_queue``.  Returns
        the bound port, or None if the listener is already running or the
        socket cannot bind.
        """
        if getattr(self, "_transfer_server", None) is not None:
            return None
        transfer = self._document_transfer()
        try:
            if callable(transfer.ensure_local_tls_material):
                transfer.ensure_local_tls_material(
                    self.storage_dir / "pikit.crt", self.storage_dir / "pikit.key"
                )
            ssl_ctx = transfer.create_server_ssl_context(
                self.storage_dir / "pikit.crt", self.storage_dir / "pikit.key"
            )
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(
                ("0.0.0.0", port if port is not None else transfer.DEFAULT_TRANSFER_PORT)
            )
            listener.listen(5)
            listener.settimeout(1.0)
        except Exception as exc:
            self.report_status(f"Transfer listener failed to start: {exc}")
            return None
        self._transfer_server = listener
        self._transfer_ssl_context = ssl_ctx
        self._transfer_stop = threading.Event()
        self._transfer_on_incoming = on_incoming
        thread = threading.Thread(target=self._transfer_accept_loop, daemon=True)
        thread.start()
        bound_port = int(listener.getsockname()[1])
        self.report_status(f"Transfer listener on port {bound_port}.")
        return bound_port

    def stop_transfer_listener(self) -> None:
        listener = getattr(self, "_transfer_server", None)
        self._transfer_stop = threading.Event()
        if listener is not None:
            self._transfer_stop.set()
            try:
                listener.close()
            except Exception:
                pass
        self._transfer_server = None

    def _transfer_accept_loop(self) -> None:
        listener = self._transfer_server
        while listener is not None and not self._transfer_stop.is_set():
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._transfer_handle_connection,
                args=(conn,),
                daemon=True,
            ).start()

    def _transfer_handle_connection(self, conn) -> None:
        transfer = self._document_transfer()
        try:
            with conn:
                with self._transfer_ssl_context.wrap_socket(conn, server_side=True) as tls_sock:
                    invite = transfer.read_json_line(tls_sock)
                    response_queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=1)
                    if self._transfer_on_incoming is not None:
                        try:
                            self._transfer_on_incoming(invite, response_queue)
                        except Exception as exc:
                            response_queue.put(
                                {"status": "error", "message": f"View handler failed: {exc}"}
                            )
                    else:
                        response_queue.put(
                            {"status": "rejected", "message": "No view handler registered."}
                        )
                    response = response_queue.get()
                    transfer.write_json_line(tls_sock, response)
        except Exception as exc:
            self.report_status(f"Incoming transfer failed: {exc}")

    def accept_incoming_document(self, invite: dict[str, Any]) -> int:
        """Fetch and import a shared document invitation (business logic)."""
        transfer = self._document_transfer()
        if not callable(transfer.fetch_shared_document):
            raise RuntimeError("Share download support is unavailable.")
        share_url = str(invite.get("share_url") or "")
        if not share_url:
            raise RuntimeError("Invitation has no share URL.")
        shared_payload = transfer.fetch_shared_document(share_url)
        return int(self.processor.import_shared_document(shared_payload))

    # ------------------------------------------------------------------
    # Async ASK (non-blocking; worker-owned SQLite connections)
    # ------------------------------------------------------------------

    def ask_question_async(
        self,
        prompt: str,
        on_done: Callable[[str | None, BaseException | None], None],
    ) -> None:
        """Run ASK off the calling thread and return the pure reply via callback.

        Thread-safety design: the command processor's memory preamble and
        breadcrumbs touch the document-store connection, which is
        main-thread-affine.  The worker therefore opens its OWN DocumentStore
        on the same db file and builds a fresh CommandProcessor over it
        (sharing the AI client); no SQLite connection is shared across
        threads, and only the reply string (or error) crosses back through
        ``on_done``, which the view marshals to its UI thread.
        """
        def _run() -> None:
            worker_store: DocumentStore | None = None
            try:
                worker_store = DocumentStore(str(self.db_path))
                worker_processor = CommandProcessor(worker_store, self.ai)
                if hasattr(worker_processor, "set_dream_handler"):
                    worker_processor.set_dream_handler(self._on_dream_event)
                reply = worker_processor.ask_question(prompt)
                on_done(reply, None)
            except Exception as exc:
                on_done(None, exc)
            finally:
                if worker_store is not None:
                    try:
                        worker_store.conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Status + lifecycle
    # ------------------------------------------------------------------

    def report_status(self, message: str) -> None:
        self.status_callback(message)

    def shutdown(self) -> None:
        """Stop background work (Dream worker thread, transfer listener)."""
        self.stop_transfer_listener()
        if self.dream_processor and hasattr(self.dream_processor, "stop"):
            try:
                self.dream_processor.stop()
            except Exception:
                pass
