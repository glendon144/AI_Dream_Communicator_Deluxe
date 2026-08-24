"""Embeddable Qt6 panes for PiKit and FunKit, hosted inside AI Navigator.

Thin views over the Stage 1 cores (``PiKit.core.PiKitCore``,
``FunKit.core.FunKitCore``): document list + viewer, command/ASK input,
status display, Dream controls (PiKit), and an explicit "Launch standalone…"
action.  No Tk calls, no duplicated business logic, no blocking work hidden
as polling: inbox consumption is scheduled with a QTimer, and status delivery
goes through a Qt signal.

Both panes import the products as packages (``PiKit.core`` / ``FunKit.core``)
so the two products coexist unambiguously in one process.  If one product's
package tree cannot be imported, its pane raises during construction and the
shell falls back to the standalone QProcess launcher for that product only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from capture_store import queue_pikit_handoff

# One product's broken tree must not prevent the other from embedding, so each
# core import is isolated.  A pane whose core is None raises in __init__.
try:
    from PiKit.core import PiKitCore
except Exception as exc:  # pragma: no cover - depends on environment
    PiKitCore = None
    _PIKIT_IMPORT_ERROR = exc
else:
    _PIKIT_IMPORT_ERROR = None

try:
    from FunKit.core import FunKitCore
except Exception as exc:  # pragma: no cover - depends on environment
    FunKitCore = None
    _FUNKIT_IMPORT_ERROR = exc
else:
    _FUNKIT_IMPORT_ERROR = None


class KitPaneBase(QWidget):
    """Shared chrome for the embedded product panes."""

    statusMessage = Signal(str)

    product_title = "Product"

    def __init__(
        self,
        root: Path | str,
        standalone_launcher: Any | None = None,
        core: Any | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.root = Path(root)
        self.standalone_launcher = standalone_launcher
        self.core = core
        self._build_ui()
        self.statusMessage.connect(self.status_label.setText)
        self.standalone_button.clicked.connect(self._launch_standalone)
        self.command_line.returnPressed.connect(self._run_command)
        self.doc_list.currentItemChanged.connect(self._on_selection_changed)
        self.refresh_docs()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.title_label = QLabel(self.product_title)
        top.addWidget(self.title_label)
        top.addStretch(1)
        self._add_top_controls(top)
        self.standalone_button = QPushButton("Launch standalone…")
        self.standalone_button.setToolTip(
            "Open this product as a separate Tk application window."
        )
        top.addWidget(self.standalone_button)
        layout.addLayout(top)

        self.splitter = QSplitter(Qt.Horizontal)
        self.doc_list = QListWidget()
        self.doc_list.setMinimumWidth(220)
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.splitter.addWidget(self.doc_list)
        self.splitter.addWidget(self.viewer)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, 1)

        self.command_line = QLineEdit()
        self.command_line.setPlaceholderText("ASK a question (Enter to send) …")
        layout.addWidget(self.command_line)

        self.status_label = QLabel("Ready.")
        layout.addWidget(self.status_label)

    def _add_top_controls(self, top: QHBoxLayout) -> None:
        """Subclass hook for product-specific toolbar controls."""

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def refresh_docs(self) -> None:
        entries = self._document_index()
        self.doc_list.blockSignals(True)
        try:
            self.doc_list.clear()
            for entry in entries:
                label = f"[{entry['id']}] {entry['title']}"
                description = entry.get("description")
                if description:
                    label += f"  —  {description}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, int(entry["id"]))
                self.doc_list.addItem(item)
        finally:
            self.doc_list.blockSignals(False)

    def _document_index(self) -> list[dict]:
        try:
            return list(self.core.doc_store.get_document_index() or [])
        except Exception as exc:
            self.statusMessage.emit(f"Document index failed: {exc}")
            return []

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        self.reveal_document(int(current.data(Qt.UserRole)))

    def reveal_document(self, doc_id: int) -> None:
        doc = self._get_document(doc_id)
        if doc is None:
            self.statusMessage.emit(f"Document {doc_id} not found.")
            return
        body = doc["body"]
        if isinstance(body, (bytes, bytearray)):
            body = bytes(body).decode("utf-8", errors="replace")
        self.viewer.setPlainText(str(body or ""))
        self.statusMessage.emit(f"Viewing: {doc['title']} (id={doc_id})")

    def _get_document(self, doc_id: int):
        try:
            return self.core.doc_store.get_document(doc_id)
        except Exception as exc:
            self.statusMessage.emit(f"Could not load document {doc_id}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Command / ASK
    # ------------------------------------------------------------------

    def _run_command(self) -> None:
        text = self.command_line.text().strip()
        if not text:
            return
        self.command_line.clear()
        self.statusMessage.emit(f"ASK: {text[:200]}")
        try:
            reply = self.core.processor.ask_question(text)
        except Exception as exc:
            self.statusMessage.emit(f"ASK failed: {exc}")
            return
        if reply:
            self.viewer.appendPlainText("\n\n── ASK reply ──\n" + str(reply))
            self.statusMessage.emit("ASK complete.")
        else:
            self.statusMessage.emit("ASK returned no reply.")

    # ------------------------------------------------------------------
    # Standalone launch
    # ------------------------------------------------------------------

    def _launch_standalone(self) -> None:
        if self.standalone_launcher is None:
            self.statusMessage.emit("Standalone launcher unavailable.")
            return
        self.statusMessage.emit("Launching standalone application…")
        self.standalone_launcher.launch_product()


class PiKitPane(KitPaneBase):
    """Embedded PiKit: document list/viewer, ASK, Dream controls, inbox."""

    product_title = "PiKit — embedded"

    INBOX_POLL_MS = 750

    def __init__(
        self,
        root: Path | str,
        standalone_launcher: Any | None = None,
        core: Any | None = None,
        parent: QWidget | None = None,
    ):
        if PiKitCore is None:
            raise RuntimeError(
                f"PiKit core unavailable: {_PIKIT_IMPORT_ERROR}"
            )
        super().__init__(
            root,
            standalone_launcher=standalone_launcher,
            core=core if core is not None else PiKitCore(root=root),
            parent=parent,
        )
        self.core.status_callback = self.statusMessage.emit
        self.timer = QTimer(self)
        self.timer.setInterval(self.INBOX_POLL_MS)
        self.timer.timeout.connect(self._poll_inbox)
        self.timer.start()
        self._sync_dream_button()

    def _add_top_controls(self, top: QHBoxLayout) -> None:
        self.dream_button = QPushButton("Dream: OFF")
        self.dream_button.clicked.connect(self._toggle_dream)
        self.dream_now_button = QPushButton("Dream Now")
        self.dream_now_button.clicked.connect(self._run_dream_now)
        top.addWidget(self.dream_button)
        top.addWidget(self.dream_now_button)

    # ----- Dream controls -----

    def _toggle_dream(self) -> None:
        self.core.set_dream_enabled(not self.core.dream_enabled)
        self._sync_dream_button()
        state = "authorized" if self.core.dream_enabled else "disabled"
        self.statusMessage.emit(f"Dream mode {state}.")

    def _sync_dream_button(self) -> None:
        if hasattr(self, "dream_button"):
            self.dream_button.setText(
                "Dream: ON" if self.core.dream_enabled else "Dream: OFF"
            )

    def _run_dream_now(self) -> None:
        try:
            capsule = self.core.run_dream_pass()
        except Exception as exc:
            self.statusMessage.emit(f"Dream pass failed: {exc}")
            return
        self.viewer.setPlainText(str(capsule))
        self.statusMessage.emit("Dream pass completed.")

    # ----- Handoff / inbox -----

    def _poll_inbox(self) -> None:
        try:
            self.core.consume_inbox_once(on_imported=self._on_handoff_imported)
        except Exception as exc:
            self.statusMessage.emit(f"Inbox poll failed: {exc}")

    def _on_handoff_imported(self, doc_id: int) -> None:
        self.refresh_docs()
        self.reveal_document(doc_id)

    def accept_handoff(self, *, packet: str, title: str, source_capture_id: int) -> None:
        """Queue a Dream Capture packet through the shared file inbox.

        The packet is written with the exact same protocol as the standalone
        path (``capture_store.queue_pikit_handoff``) and claimed atomically by
        the rename-based inbox consumer, so an embedded pane and a standalone
        PiKit process can never import the same packet twice.
        """
        queued = queue_pikit_handoff(
            self.core.inbox_dir,
            title=title,
            body=packet,
            source_capture_id=source_capture_id,
        )
        self.statusMessage.emit(f"Dream Capture queued: {queued.name}")


class FunKitPane(KitPaneBase):
    """Embedded FunKit: document list/viewer, ASK, in-process handoff import."""

    product_title = "FunKit — embedded"

    def __init__(
        self,
        root: Path | str,
        standalone_launcher: Any | None = None,
        core: Any | None = None,
        parent: QWidget | None = None,
    ):
        if FunKitCore is None:
            raise RuntimeError(
                f"FunKit core unavailable: {_FUNKIT_IMPORT_ERROR}"
            )
        super().__init__(
            root,
            standalone_launcher=standalone_launcher,
            core=core if core is not None else FunKitCore(root=root),
            parent=parent,
        )
        self.core.status_callback = self.statusMessage.emit

    def _add_top_controls(self, top: QHBoxLayout) -> None:
        # Dream controls, provider UI, RAG, OPML menus etc. are Stage 3.
        pass

    def accept_handoff(self, *, packet: str, title: str, source_capture_id: int) -> None:
        """Import a Dream Capture packet in-process via the core.

        The packet shape is the same external contract as the clipboard flow
        (unchanged: the shell still copies the packet to the clipboard for the
        standalone paste path); the embedded pane additionally imports it
        through ``FunKitCore.import_handoff_payload``.
        """
        new_id = self.core.import_handoff_payload(
            {
                "version": 1,
                "kind": "dream_capture",
                "title": title,
                "body": packet,
                "source_capture_id": source_capture_id,
            }
        )
        self.refresh_docs()
        self.reveal_document(new_id)
        self.statusMessage.emit(f"Imported Dream Capture as document {new_id}.")
