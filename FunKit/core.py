"""FunKitCore — GUI-agnostic application core for FunKit.

Owns the non-visual application lifecycle and business objects that the Tk
GUI (and a future Qt6 pane) render as views:

* document store, AI interface (provider wiring), command processor
* settings/configuration persistence
* local Dream memory processing + optional Dream/OpenBrain publishing
* archive-export memory publishing
* status reporting through a callback rather than direct Tk calls

The core is scheduler-neutral: it imports no tkinter/Qt and exposes only
one-shot methods; views decide how they are scheduled.

Paths are explicit and default to locations under the product root, so
correctness does not depend on the process working directory.

Note: FunKit has no handoff inbox today (Dream Capture reaches FunKit via the
clipboard), so unlike PiKitCore this core does not poll one.  It exposes the
shared packet-import entry point through ``import_handoff_payload`` for the
future embedded consumer.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Dual-mode imports: standalone ``python main.py`` resolves the top-level
# ``modules`` package (FunKit dir on sys.path); in-process embedding imports
# this module as ``FunKit.core``, where the package-relative forms are used.
try:
    from modules.command_processor import CommandProcessor
    from modules.document_store import DEFAULT_DB_PATH, DocumentStore
except ImportError:
    from .modules.command_processor import CommandProcessor
    from .modules.document_store import DEFAULT_DB_PATH, DocumentStore

DEFAULT_SETTINGS_FILE = "funkit_settings.json"
DEFAULT_DREAMS_DB_PATH = Path("storage") / "funkit_dreams.sqlite3"


@dataclass
class CommandResult:
    """Result of a ``$`` command executed by ``FunKitCore.run_command``.

    Views use this to decide what to reveal or store:

    * ``output``/``output_title``: text the view may store as a new document
      (mirroring the Tk app's ``store_output``) and reveal.
    * ``reveal_doc_id``: a document the view should refresh and reveal.
    * ``needs_input``: the command needs the user to supply text (``EDIT``);
      the view prompts and re-invokes ``run_command`` with ``extra_text``.
    """

    handled: bool
    output: str = ""
    output_title: str | None = None
    reveal_doc_id: int | None = None
    needs_input: bool = False
    input_doc_id: int | None = None
    input_prompt: str = ""


def _null_status(message: str) -> None:
    pass


class FunKitCore:
    """Application core for FunKit (business objects + lifecycle)."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        db_path: Path | str | None = None,
        settings_file: Path | str | None = None,
        dreams_db_path: Path | str | None = None,
        status: Callable[[str], None] | None = None,
        store: DocumentStore | None = None,
        ai: Any | None = None,
        processor: CommandProcessor | None = None,
    ):
        # Explicit paths (default under the product root, not the CWD).
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent
        self.storage_dir = self.root / "storage"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = (
            Path(db_path)
            if db_path is not None
            else self.storage_dir / DEFAULT_DB_PATH.name
        )
        self.settings_file = (
            Path(settings_file)
            if settings_file is not None
            else self.root / DEFAULT_SETTINGS_FILE
        )
        self.status_callback: Callable[[str], None] = (
            status if status is not None else _null_status
        )

        # Settings / configuration (shared dict; the Tk view mutates it and
        # calls save_settings()).
        self.settings: dict[str, Any] = self._load_settings()
        self.dreams_db_path = (
            Path(dreams_db_path)
            if dreams_db_path is not None
            else Path(str(self.settings.get("dreams_db_path", DEFAULT_DREAMS_DB_PATH)))
        )
        self.archive_memory_enabled: bool = bool(
            self.settings.get("archive_memory_enabled", True)
        )
        self.archive_publish_to_dream: bool = bool(
            self.settings.get("archive_publish_to_dream", False)
        )
        self.archive_publish_to_openbrain: bool = bool(
            self.settings.get("archive_publish_to_openbrain", False)
        )
        self.archive_memory_ttl_seconds: int | None = self.settings.get(
            "archive_memory_ttl_seconds"
        )
        self._memory_publish_adapter: Any | None = None

        # The provider registry defaults to CWD-relative paths and writes its
        # defaults at import time; point it at this core's explicit storage
        # dir BEFORE anything imports it, so embedding (shell CWD != FunKit
        # root) reads/writes FunKit/storage/providers.json.  Standalone
        # launches are unaffected (configured dir == CWD default).
        os.environ.setdefault("FUNKIT_STORAGE_DIR", str(self.storage_dir))
        try:
            from modules.provider_registry import configure_paths
        except ImportError:
            from .modules.provider_registry import configure_paths
        configure_paths(str(self.storage_dir))

        # Business objects (mirrors what main.py previously assembled via
        # modules.app_runtime.build_processor).
        if store is not None and processor is not None:
            self.doc_store = store
            self.processor = processor
            self.ai = ai
        else:
            try:
                from modules.app_runtime import build_processor
            except ImportError:
                from .modules.app_runtime import build_processor

            if store is None:
                store = DocumentStore(str(self.db_path))
            built_store, built_ai, built_processor = build_processor(store=store)
            self.doc_store = built_store
            self.ai = built_ai
            self.processor = built_processor

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self) -> dict[str, Any]:
        try:
            if self.settings_file.exists():
                data = json.loads(self.settings_file.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def save_settings(self) -> None:
        try:
            self.settings_file.write_text(
                json.dumps(self.settings, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            print("[WARN] Could not save settings:", exc)

    # ------------------------------------------------------------------
    # Dream / memory publishing
    # ------------------------------------------------------------------

    def get_memory_publish_adapter(self) -> Any | None:
        """Return the (lazily built) FunKitDreamAdapter, or None.

        Mirrors the Tk GUI's original lazy construction, including its import
        strategy (``memory_publish_adapter`` / ``dream`` module names) and its
        status messages.  Publishing to a networked Dream server requires
        ``DREAM_BASE_URL`` (settings or environment); without a server the
        adapter still records events into local dream memory.
        """
        if self._memory_publish_adapter is not None:
            return self._memory_publish_adapter

        if not self.archive_memory_enabled:
            return None

        try:
            from memory_publish_adapter import (
                DreamServerPublisher,
                FunKitDreamAdapter,
                OpenBrainPublisher,
            )
        except ImportError:
            try:
                from .modules.memory_publish_adapter import (
                    DreamServerPublisher,
                    FunKitDreamAdapter,
                    OpenBrainPublisher,
                )
            except Exception as exc:
                self.report_status(f"Archive memory adapter unavailable: {exc}")
                return None
        except Exception as exc:
            self.report_status(f"Archive memory adapter unavailable: {exc}")
            return None

        try:
            dream_module = __import__("dream", fromlist=["DreamProcessor"])
            DreamProcessor = getattr(dream_module, "DreamProcessor")
        except Exception:
            try:
                dream_module = __import__(
                    "PiKit.modules.dream", fromlist=["DreamProcessor"]
                )
                DreamProcessor = getattr(dream_module, "DreamProcessor")
            except Exception as exc:
                self.report_status(f"DreamProcessor unavailable: {exc}")
                return None

        dreams_db_path = str(self.dreams_db_path)
        try:
            dream_processor = DreamProcessor(dreams_db_path=dreams_db_path)
        except Exception as exc:
            self.report_status(f"Could not initialize DreamProcessor: {exc}")
            return None

        dream_publisher = None
        dream_base_url = self.settings.get("dream_base_url") or os.environ.get(
            "DREAM_BASE_URL"
        )
        if dream_base_url:
            try:
                from dream_client import DreamClient

                dream_publisher = DreamServerPublisher(
                    DreamClient(base_url=dream_base_url)
                )
            except Exception as exc:
                self.report_status(f"Dream publish disabled: {exc}")

        openbrain_publisher = None
        openbrain_base_url = self.settings.get("openbrain_base_url") or os.environ.get(
            "OPENBRAIN_BASE_URL"
        )
        openbrain_access_token = self.settings.get(
            "openbrain_access_token"
        ) or os.environ.get("OPENBRAIN_ACCESS_TOKEN")
        if openbrain_base_url and openbrain_access_token:
            try:
                from openbrain_client import OpenBrainClient

                openbrain_publisher = OpenBrainPublisher(
                    OpenBrainClient(
                        base_url=openbrain_base_url,
                        access_token=openbrain_access_token,
                    )
                )
            except Exception as exc:
                self.report_status(f"OpenBrain publish disabled: {exc}")

        self._memory_publish_adapter = FunKitDreamAdapter(
            processor=dream_processor,
            dream_publisher=dream_publisher,
            openbrain_publisher=openbrain_publisher,
        )
        return self._memory_publish_adapter

    def archive_after_export(
        self,
        *,
        title: str,
        content: str,
        doc_id: int | None = None,
        export_path: str | None = None,
        publish_to_dream: bool | None = None,
        publish_to_openbrain: bool | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        """Record an archive export into local dream memory (and publishers).

        Mirrors the Tk GUI's ``_archive_memory_after_export`` flow.  Returns
        the publish result dict, or None when archive memory is disabled or
        the adapter is unavailable.  Status is reported through the callback.
        """
        adapter = self.get_memory_publish_adapter()
        if adapter is None:
            return None

        publish_to_dream = (
            self.archive_publish_to_dream
            if publish_to_dream is None
            else publish_to_dream
        )
        publish_to_openbrain = (
            self.archive_publish_to_openbrain
            if publish_to_openbrain is None
            else publish_to_openbrain
        )
        ttl_seconds = (
            self.archive_memory_ttl_seconds if ttl_seconds is None else ttl_seconds
        )

        snippet = str(content or "").strip()
        if len(snippet) > 4000:
            snippet = snippet[:4000]

        metadata = {
            "ui_action": "archive_export",
            "doc_title": title,
            "doc_id": doc_id,
            "export_path": export_path,
        }

        try:
            adapter.note_archive_event(
                snippet or f"Exported document: {title}",
                source_doc_id=doc_id,
                metadata=metadata,
            )
            result = adapter.publish_latest(
                title=f"FunKit archive export: {title}",
                publish_to_dream=publish_to_dream,
                publish_to_openbrain=publish_to_openbrain,
                ttl_seconds=ttl_seconds,
            )
        except Exception as exc:
            self.report_status(f"Archive memory publish failed: {exc}")
            return None

        destinations = ["local dream memory"]
        if publish_to_dream:
            destinations.append("Dream")
        if publish_to_openbrain:
            destinations.append("OpenBrain")
        self.report_status(f"Archive noted to {', '.join(destinations)}")
        return result

    # ------------------------------------------------------------------
    # Handoff (future embedded consumer)
    # ------------------------------------------------------------------

    def import_handoff_payload(self, payload: dict[str, Any]) -> int:
        """Import a Dream Capture handoff packet into the document store.

        FunKit has no inbox today, but this shared entry point keeps the
        packet protocol consistent with PiKit's for the future embedded pane.

        The packet schema mirrors ``PiKit/dream_capture_inbox.py``
        (``import_handoff_payload``); it is kept inline here so FunKit
        standalone does not depend on PiKit being importable.  Both products
        consume the same ``kind``/``version`` packet format written by
        ``ai_navigator/capture_store.py``.
        """
        if payload.get("kind") != "dream_capture" or payload.get("version") != 1:
            raise ValueError(
                f"Unsupported FunKit handoff: {payload.get('kind')!r} v{payload.get('version')}"
            )
        title = str(payload.get("title") or "Dream Capture").strip()
        body = str(payload.get("body") or "")
        if not body.strip():
            raise ValueError("Dream Capture has no document body")
        # FunKit's CommandProcessor has no import_shared_document (that is a
        # PiKit document-share feature); the packet import is a plain document
        # insert, identical to PiKit's end result.
        return int(self.doc_store.add_document(title, body))

    # ------------------------------------------------------------------
    # Dream / memory controls
    # ------------------------------------------------------------------

    def set_archive_memory_enabled(self, enabled: bool) -> None:
        self.archive_memory_enabled = bool(enabled)
        self.settings["archive_memory_enabled"] = self.archive_memory_enabled
        self.save_settings()

    def set_archive_publish_to_dream(self, enabled: bool) -> None:
        self.archive_publish_to_dream = bool(enabled)
        self.settings["archive_publish_to_dream"] = self.archive_publish_to_dream
        self.save_settings()

    def set_archive_publish_to_openbrain(self, enabled: bool) -> None:
        self.archive_publish_to_openbrain = bool(enabled)
        self.settings["archive_publish_to_openbrain"] = self.archive_publish_to_openbrain
        self.save_settings()

    def run_dream_pass(self) -> str:
        """Run a Dream pass now via the memory-publish adapter and return the capsule."""
        adapter = self.get_memory_publish_adapter()
        if adapter is None:
            raise RuntimeError("Dream processor is unavailable.")
        processor = getattr(adapter, "processor", None)
        if processor is None or not hasattr(processor, "force_dream_pass"):
            raise RuntimeError("Dream processor is unavailable.")
        return str(processor.force_dream_pass())

    def get_memory(self, key: str = "global") -> dict[str, Any]:
        """Read the ai_memory record for a key (viewed/edited by the UI)."""
        try:
            from modules.ai_memory import get_memory as _get_memory
        except ImportError:
            from .modules.ai_memory import get_memory as _get_memory
        conn = getattr(self.doc_store, "conn", None)
        if conn is None:
            return {}
        try:
            mem = _get_memory(conn, key=key)
            return mem if isinstance(mem, dict) else {}
        except Exception:
            return {}

    def set_memory(self, data: dict[str, Any], key: str = "global") -> None:
        """Persist the ai_memory record for a key."""
        try:
            from modules.ai_memory import set_memory as _set_memory
        except ImportError:
            from .modules.ai_memory import set_memory as _set_memory
        conn = getattr(self.doc_store, "conn", None)
        if conn is None:
            return
        try:
            _set_memory(conn, data, key=key)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Provider controls + RAG (business state; view renders the widgets)
    # ------------------------------------------------------------------

    def _provider_registry(self):
        try:
            from modules.provider_registry import registry
        except ImportError:
            from .modules.provider_registry import registry
        return registry

    def list_providers(self) -> list[tuple[str, str]]:
        """Return [(key, label), ...] in providers.json order."""
        try:
            return list(self._provider_registry().list_labels())
        except Exception as exc:
            self.report_status(f"Provider list unavailable: {exc}")
            return []

    def get_selected_provider(self) -> str:
        try:
            return self._provider_registry().read_selected()
        except Exception:
            return ""

    def set_provider(self, key: str) -> bool:
        """Switch the AI provider, persist the selection, save settings.

        Unknown keys are rejected (the view only offers keys from
        ``list_providers``); ``registry.get`` alone would silently fall back
        to the default provider.
        """
        try:
            registry = self._provider_registry()
            if not any(k == key for k, _ in registry.list_labels()):
                return False
            cfg = registry.get(key)
            registry.write_selected(key)
            ai = getattr(self.processor, "ai", None)
            if ai is not None and hasattr(ai, "set_provider"):
                ai.set_provider(key, cfg.model)
            self.settings["selected_provider"] = key
            self.save_settings()
            self.report_status(f"Switched provider to {cfg.label} • {cfg.model}")
            return True
        except Exception as exc:
            self.report_status(f"Provider switch failed: {exc}")
            return False

    def set_rag_enabled(self, enabled: bool) -> None:
        """Mirror the Tk app's RAG toggle (processor attr when no setter)."""
        processor = self.processor
        if hasattr(processor, "set_rag_enabled"):
            processor.set_rag_enabled(enabled)
        else:
            setattr(processor, "rag_enabled", enabled)

    def is_rag_enabled(self) -> bool:
        processor = self.processor
        if hasattr(processor, "is_rag_enabled"):
            return bool(processor.is_rag_enabled())
        return bool(getattr(processor, "rag_enabled", False))

    # ------------------------------------------------------------------
    # $ commands (parity with the Tk app's built-in command set)
    # ------------------------------------------------------------------

    def run_command(
        self, cmdline: str, extra_text: str | None = None
    ) -> CommandResult:
        """Execute a ``$`` command against the core's business objects.

        Mirrors the Tk app's built-in command set (HELP/NEW/LIST/VIEW/EDIT/
        DELETE/SAVE/LOAD/ASK/SUMMARIZE), dispatching into ``doc_store`` and
        ``processor`` — no parallel parser is created in the Qt pane.  The
        legacy pandas-based ``modules.commands`` fallback is deliberately not
        ported (it is a separate CLI parser with its own dependencies).
        """
        import shlex

        try:
            argv = shlex.split(cmdline)
        except Exception:
            argv = cmdline.split()
        if not argv:
            return CommandResult(handled=False, output="[no handler matched]")
        # Tolerate a leading ``$`` (the Tk app strips it before dispatch).
        if argv[0] == "$":
            argv = argv[1:]
        if not argv:
            return CommandResult(handled=False, output="[no handler matched]")

        cmd = argv[0].upper()

        def _doc_body(doc_id: int) -> str:
            row = self.doc_store.get_document(doc_id)
            if not row:
                raise ValueError(f"Document {doc_id} not found")
            if isinstance(row, dict):
                return str(row.get("body") or "")
            if hasattr(row, "keys"):  # sqlite3.Row: supports keys()/[], not .get()
                return str(row["body"] or "")
            if isinstance(row, (list, tuple)) and len(row) >= 3:
                return str(row[2] or "")
            return str(row)

        if cmd == "HELP":
            return CommandResult(
                handled=True,
                output=(
                    "FunKit command cheatsheet (type in the top bar prefixed with $):\n\n"
                    "  NEW <title>                   Create a new empty document\n"
                    "  LIST                          List documents (id, title)\n"
                    "  VIEW <id>                     Open a document by id\n"
                    "  EDIT <id>                     Append text to a document (prompt)\n"
                    "  DELETE <id>                   Delete a document\n"
                    "  SAVE <id> <path>              Save a document body to a file\n"
                    "  LOAD <path>                   Import a text file as a new document\n"
                    "  ASK <question>                Ask current provider (AI) a question\n"
                    "  SUMMARIZE <id>                Summarize the given document with AI\n"
                ),
                output_title="$ HELP",
            )

        if cmd == "NEW":
            title = " ".join(argv[1:]).strip() or "Untitled"
            new_id = int(self.doc_store.add_document(title, ""))
            return CommandResult(handled=True, reveal_doc_id=new_id)

        if cmd == "LIST":
            lines = []
            for row in self.doc_store.get_document_index() or []:
                did = row.get("id") if isinstance(row, dict) else (
                    row[0] if isinstance(row, (list, tuple)) else None
                )
                ttl = row.get("title") if isinstance(row, dict) else (
                    row[1] if isinstance(row, (list, tuple)) else ""
                )
                lines.append(f"{did:>4}  {ttl}")
            return CommandResult(
                handled=True,
                output="\n".join(lines) or "[no documents]",
                output_title="$ LIST",
            )

        if cmd == "VIEW" and len(argv) >= 2 and argv[1].isdigit():
            doc_id = int(argv[1])
            if self.doc_store.get_document(doc_id):
                return CommandResult(handled=True, reveal_doc_id=doc_id)
            return CommandResult(
                handled=True, output=f"Document {doc_id} not found", output_title="$ VIEW"
            )

        if cmd == "EDIT" and len(argv) >= 2 and argv[1].isdigit():
            doc_id = int(argv[1])
            if extra_text is None:
                return CommandResult(
                    handled=True,
                    needs_input=True,
                    input_doc_id=doc_id,
                    input_prompt=f"Append to document {doc_id}:",
                )
            try:
                body = _doc_body(doc_id)
                self.doc_store.update_document(
                    doc_id, body + ("\n" if body and extra_text else "") + extra_text
                )
                return CommandResult(handled=True, reveal_doc_id=doc_id)
            except Exception as exc:
                return CommandResult(
                    handled=True, output=f"[error] {exc}", output_title="$ EDIT"
                )

        if cmd == "DELETE" and len(argv) >= 2 and argv[1].isdigit():
            doc_id = int(argv[1])
            try:
                self.doc_store.delete_document(doc_id)
                return CommandResult(handled=True, output=f"Deleted document {doc_id}")
            except Exception as exc:
                return CommandResult(
                    handled=True, output=f"[error] {exc}", output_title="$ DELETE"
                )

        if cmd == "SAVE" and len(argv) >= 3 and argv[1].isdigit():
            doc_id = int(argv[1])
            path = argv[2]
            try:
                Path(path).write_text(_doc_body(doc_id), encoding="utf-8")
                return CommandResult(
                    handled=True,
                    output=f"Saved {doc_id} → {path}",
                    output_title="$ SAVE",
                )
            except Exception as exc:
                return CommandResult(
                    handled=True, output=f"[error] {exc}", output_title="$ SAVE"
                )

        if cmd == "LOAD" and len(argv) >= 2:
            path = " ".join(argv[1:])
            try:
                content = Path(path).read_text(encoding="utf-8", errors="replace")
                new_id = int(self.doc_store.add_document(Path(path).name, content))
                return CommandResult(handled=True, reveal_doc_id=new_id)
            except Exception as exc:
                return CommandResult(
                    handled=True, output=f"[error] {exc}", output_title="$ LOAD"
                )

        if cmd == "ASK":
            question = " ".join(argv[1:]).strip()
            if not question:
                return CommandResult(
                    handled=True, output="Usage: ASK <question>", output_title="$ ASK"
                )
            try:
                reply = self.processor.ask_question(question)
            except Exception as exc:
                reply = f"[error] {exc}"
            return CommandResult(
                handled=True,
                output=reply or "[no reply]",
                output_title=f"ASK: {question}",
            )

        if cmd == "SUMMARIZE" and len(argv) >= 2 and argv[1].isdigit():
            doc_id = int(argv[1])
            try:
                text = _doc_body(doc_id)
                reply = self.processor.ask_question(
                    f"Please summarize the following document:\n{text}"
                )
            except Exception as exc:
                reply = f"[error] {exc}"
            return CommandResult(
                handled=True,
                output=reply or "[no reply]",
                output_title=f"Summary of {doc_id}",
            )

        return CommandResult(handled=False, output="[no handler matched]")

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
                if hasattr(self, "_on_dream_event") and hasattr(
                    worker_processor, "set_dream_handler"
                ):
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
