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
    # Status + lifecycle
    # ------------------------------------------------------------------

    def report_status(self, message: str) -> None:
        self.status_callback(message)

    def shutdown(self) -> None:
        """Stop background work (Dream worker thread)."""
        if self.dream_processor and hasattr(self.dream_processor, "stop"):
            try:
                self.dream_processor.stop()
            except Exception:
                pass
