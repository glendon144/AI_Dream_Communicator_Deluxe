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

        # Business objects (mirrors what main.py previously assembled via
        # modules.app_runtime.build_processor).
        if store is not None and processor is not None:
            self.doc_store = store
            self.processor = processor
            self.ai = ai
        else:
            # The provider registry defaults to CWD-relative paths and writes
            # its defaults at import time; point it at this core's explicit
            # storage dir BEFORE anything imports it, so embedding (shell CWD
            # != FunKit root) reads/writes FunKit/storage/providers.json.
            os.environ.setdefault("FUNKIT_STORAGE_DIR", str(self.storage_dir))

            try:
                from modules.app_runtime import build_processor
            except ImportError:
                from .modules.app_runtime import build_processor

            try:
                from modules.provider_registry import configure_paths
            except ImportError:
                from .modules.provider_registry import configure_paths
            configure_paths(str(self.storage_dir))

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
    # Status + lifecycle
    # ------------------------------------------------------------------

    def report_status(self, message: str) -> None:
        self.status_callback(message)
