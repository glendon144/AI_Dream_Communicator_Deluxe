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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
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

    # Marshals ASK results from the worker thread to the GUI thread.
    askFinished = Signal(object, object)

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
        self.current_doc_id: int | None = None
        self._build_ui()
        self.statusMessage.connect(self.status_label.setText)
        self.askFinished.connect(self._on_ask_finished)
        self.standalone_button.clicked.connect(self._launch_standalone)
        self.command_line.returnPressed.connect(self._run_command)
        self.doc_list.currentItemChanged.connect(self._on_selection_changed)
        self.export_menu.addAction("Save As Text…", self._save_as_text)
        self.export_menu.addAction("Export Document…", self._export_document)
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
        self.export_button = QPushButton("Export ▾")
        self.export_menu = QMenu(self)
        self.export_button.setMenu(self.export_menu)
        top.addWidget(self.export_button)
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
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderLabels(["Outline"])
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.viewer)
        self.content_stack.addWidget(self.outline_tree)
        self.content_stack.addWidget(self.image_label)
        self.splitter.addWidget(self.doc_list)
        self.splitter.addWidget(self.content_stack)
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
        if self._render_image(body):
            self.current_doc_id = int(doc_id)
            self.statusMessage.emit(f"Viewing image: {doc['title']} (id={doc_id})")
            return
        if isinstance(body, (bytes, bytearray)):
            body = bytes(body).decode("utf-8", errors="replace")
        body_text = str(body or "")
        if self._looks_like_opml(body_text):
            self._render_opml_outline(body_text)
            self.content_stack.setCurrentWidget(self.outline_tree)
        else:
            self.viewer.setPlainText(body_text)
            self.content_stack.setCurrentWidget(self.viewer)
        self.current_doc_id = int(doc_id)
        self.statusMessage.emit(f"Viewing: {doc['title']} (id={doc_id})")

    def _render_image(self, body) -> bool:
        """Present binary/data-URI image bodies as a QPixmap (presentation only)."""
        import base64

        pix = QPixmap()
        if isinstance(body, (bytes, bytearray)) and bytes(body):
            pix.loadFromData(bytes(body))
        elif isinstance(body, str) and body.strip().startswith("data:image/"):
            try:
                _meta, b64 = body.strip().split(",", 1)
                pix.loadFromData(base64.b64decode(b64))
            except Exception:
                pix = QPixmap()
        if pix.isNull():
            return False
        width = max(self.viewer.width(), 200)
        self.image_label.setPixmap(
            pix.scaledToWidth(width, Qt.SmoothTransformation)
        )
        self.content_stack.setCurrentWidget(self.image_label)
        return True

    @staticmethod
    def _looks_like_opml(text: str) -> bool:
        head = text.strip()[:200].lower()
        return "<opml" in head or (head.startswith("<?xml") and "<opml" in text.lower())

    def _render_opml_outline(self, xml_text: str) -> None:
        """Present OPML XML as an expandable tree (presentation only)."""
        import xml.etree.ElementTree as ET

        self.outline_tree.clear()
        try:
            root = ET.fromstring(xml_text.strip())
        except Exception:
            self.outline_tree.addTopLevelItem(QTreeWidgetItem(["[unparsable OPML]"]))
            return

        def walk(node, parent_item):
            tag = (node.tag or "").lower()
            if tag.endswith("outline"):
                text = node.attrib.get("text") or node.attrib.get("title") or ""
                item = QTreeWidgetItem([text])
                if parent_item is None:
                    self.outline_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                for child in list(node):
                    walk(child, item)
            else:
                for child in list(node):
                    walk(child, parent_item)

        walk(root, None)

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
        # ``$`` commands are delegated to the core's command dispatcher (no
        # parallel parser in the pane); anything else is an ASK.
        if text.startswith("$") and hasattr(self.core, "run_command"):
            self._run_dollar_command(text)
            return
        self._ask(text)

    def _ask(self, text: str) -> None:
        self.statusMessage.emit(f"ASK: {text[:200]}")
        if hasattr(self.core, "ask_question_async"):
            # Non-blocking: worker thread + worker-owned SQLite connections;
            # the reply is marshaled back through the askFinished signal.
            self.core.ask_question_async(text, self._ask_done)
        else:
            try:
                reply = self.core.processor.ask_question(text)
            except Exception as exc:
                self.statusMessage.emit(f"ASK failed: {exc}")
                return
            self._on_ask_finished(reply, None)

    def _ask_done(self, reply, error) -> None:
        # Runs on the ASK worker thread → marshal to the GUI thread.
        self.askFinished.emit(reply, error)

    def _on_ask_finished(self, reply, error) -> None:
        if error is not None:
            self.statusMessage.emit(f"ASK failed: {error}")
            return
        if reply:
            self.viewer.appendPlainText("\n\n── ASK reply ──\n" + str(reply))
            self.statusMessage.emit("ASK complete.")
        else:
            self.statusMessage.emit("ASK returned no reply.")

    def _run_dollar_command(self, text: str) -> None:
        result = self.core.run_command(text[1:].strip())
        if not result.handled:
            self.statusMessage.emit(result.output or "[no handler matched]")
            return
        if result.needs_input and result.input_doc_id is not None:
            extra, ok = QInputDialog.getText(
                self, "EDIT", result.input_prompt
            )
            if not ok:
                return
            result = self.core.run_command(
                text[1:].strip(), extra_text=extra
            )
            if not result.handled:
                self.statusMessage.emit(result.output)
                return
        # Materialize command output as a document (mirrors the Tk app's
        # store_output) and reveal any document the command touched.
        if result.output_title and result.output:
            try:
                new_id = int(
                    self.core.doc_store.add_document(
                        result.output_title, result.output
                    )
                )
                self.refresh_docs()
                self.reveal_document(new_id)
                return
            except Exception as exc:
                self.statusMessage.emit(f"Command output store failed: {exc}")
        self.refresh_docs()
        if result.reveal_doc_id is not None:
            self.reveal_document(result.reveal_doc_id)
        elif result.output:
            self.statusMessage.emit(result.output)

    # ------------------------------------------------------------------
    # Export / save-as-text (Qt-native dialogs over core business methods)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_filename(title: str) -> str:
        safe = "".join(
            c if (c.isalnum() or c in "._- ") else "_" for c in (title or "Document")
        ).strip()
        return safe or "Document"

    def _current_doc_id(self) -> int | None:
        if self.current_doc_id is not None:
            return self.current_doc_id
        item = self.doc_list.currentItem()
        if item is not None:
            return int(item.data(Qt.UserRole))
        return None

    def _save_as_text(self) -> None:
        doc_id = self._current_doc_id()
        if doc_id is None:
            self.statusMessage.emit("No document selected.")
            return
        try:
            title, text = self.core.document_to_plain_text(doc_id)
        except Exception as exc:
            self.statusMessage.emit(f"Save as text failed: {exc}")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As Text",
            self._safe_filename(title) + ".txt",
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(text + "\n", encoding="utf-8", newline="\n")
            self.statusMessage.emit(f"Saved text: {path}")
        except Exception as exc:
            self.statusMessage.emit(f"Save failed: {exc}")

    def _export_document(self) -> None:
        doc_id = self._current_doc_id()
        if doc_id is None:
            self.statusMessage.emit("No document selected.")
            return
        title = ""
        try:
            doc = self.core.doc_store.get_document(doc_id)
            title = str(doc["title"] or "document") if doc else "document"
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Document",
            self._safe_filename(title),
            "All files (*)",
        )
        if not path:
            return
        try:
            self.core.export_document_to_path(doc_id, path)
            self.statusMessage.emit(f"Exported: {path}")
        except Exception as exc:
            self.statusMessage.emit(f"Export failed: {exc}")

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

    # Marshals transfer invitations from the listener thread to the GUI thread.
    transferPrompted = Signal(dict, object)

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
        self.transferPrompted.connect(self._handle_transfer_prompt)
        self.core.start_transfer_listener(on_incoming=self._on_incoming_transfer)
        self._sync_dream_button()

    def _add_top_controls(self, top: QHBoxLayout) -> None:
        self.dream_button = QPushButton("Dream: OFF")
        self.dream_button.clicked.connect(self._toggle_dream)
        self.dream_now_button = QPushButton("Dream Now")
        self.dream_now_button.clicked.connect(self._run_dream_now)
        top.addWidget(self.dream_button)
        top.addWidget(self.dream_now_button)
        self.opml_button = QPushButton("OPML ▾")
        self.opml_menu = QMenu(self)
        self.opml_menu.addAction("Convert Current → OPML", self._opml_convert_current)
        self.opml_menu.addAction("Batch Convert Selected → OPML", self._opml_batch_convert)
        self.opml_menu.addAction("URL → OPML…", self._opml_import_url)
        self.opml_menu.addAction("Crawl OPML…", self._opml_crawl)
        self.opml_button.setMenu(self.opml_menu)
        top.addWidget(self.opml_button)

    # ----- OPML actions (business conversions via the core) -----

    def _opml_convert_current(self) -> None:
        doc_id = self._current_doc_id()
        if doc_id is None:
            self.statusMessage.emit("No document selected.")
            return
        try:
            new_id = self.core.convert_document_to_opml(doc_id)
        except Exception as exc:
            self.statusMessage.emit(f"Convert → OPML failed: {exc}")
            return
        self.refresh_docs()
        self.reveal_document(new_id)
        self.statusMessage.emit("Converted 1 document.")

    def _opml_batch_convert(self) -> None:
        ids = [
            int(self.doc_list.item(i).data(Qt.UserRole))
            for i in range(self.doc_list.count())
        ]
        if not ids:
            self.statusMessage.emit("No documents selected.")
            return
        converted, failed = self.core.batch_convert_documents_to_opml(ids)
        self.refresh_docs()
        if failed:
            self.statusMessage.emit(
                f"Converted {converted} document(s); {failed} failed."
            )
        else:
            self.statusMessage.emit(f"Converted {converted} document(s).")

    def _opml_import_url(self) -> None:
        url, ok = QInputDialog.getText(
            self, "URL → OPML", "Enter a URL to import as OPML:"
        )
        if not ok or not url.strip():
            return
        try:
            new_id = self.core.import_url_as_opml(url.strip())
        except Exception as exc:
            self.statusMessage.emit(f"URL → OPML failed: {exc}")
            return
        self.refresh_docs()
        self.reveal_document(new_id)
        self.statusMessage.emit("Imported URL as OPML.")

    def _opml_crawl(self) -> None:
        seed, ok = QInputDialog.getText(
            self, "Crawl OPML", "Enter an OPML seed URL or path:"
        )
        if not ok or not seed.strip():
            return
        depth, ok_depth = QInputDialog.getInt(
            self, "Crawl OPML", "Max depth:", 2, 1, 10
        )
        if not ok_depth:
            return
        try:
            new_ids = self.core.crawl_opml(seed.strip(), max_depth=depth)
        except Exception as exc:
            self.statusMessage.emit(f"Crawl failed: {exc}")
            return
        self.refresh_docs()
        self.statusMessage.emit(f"Imported {len(new_ids)} document(s) from crawl.")

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

    # ----- Transfer listener prompts (marshaled via a Qt signal) -----

    def _on_incoming_transfer(self, invite: dict, response_queue) -> None:
        """Runs on the listener thread; marshal the prompt to the GUI thread."""
        self.transferPrompted.emit(invite, response_queue)

    def _handle_transfer_prompt(self, invite: dict, response_queue) -> None:
        sender = str(invite.get("sender_name") or "PiKit user")
        title = str(invite.get("doc_title") or "Untitled document")
        accepted = (
            QMessageBox.question(
                self,
                "Incoming Document",
                f"{sender} wants to send you:\n\n{title}\n\nAccept this document?",
            )
            == QMessageBox.Yes
        )
        if not accepted:
            response_queue.put(
                {"status": "rejected", "message": "The recipient declined the document transfer."}
            )
            return
        try:
            new_id = self.core.accept_incoming_document(invite)
            self.refresh_docs()
            self.reveal_document(new_id)
            response_queue.put(
                {"status": "accepted", "message": "The recipient accepted the document.",
                 "imported_doc_id": int(new_id)}
            )
        except Exception as exc:
            response_queue.put({"status": "error", "message": str(exc)})

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
        # Provider selector + RAG (Qt widgets over core business state).
        self.provider_combo = QComboBox()
        for key, label in self.core.list_providers():
            self.provider_combo.addItem(label, key)
        selected = self.core.get_selected_provider()
        idx = self.provider_combo.findData(selected)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.rag_checkbox = QCheckBox("RAG")
        self.rag_checkbox.setChecked(self.core.is_rag_enabled())
        self.rag_checkbox.toggled.connect(self.core.set_rag_enabled)
        top.addWidget(self.provider_combo)
        top.addWidget(self.rag_checkbox)
        # Dream / memory controls.
        self.memory_button = QPushButton("Memory ▾")
        self.memory_menu = QMenu(self)
        self.memory_menu.addAction("Dream Now", self._run_dream_now)
        self.memory_menu.addAction("Memory…", self._open_memory_dialog)
        self.memory_menu.addSeparator()
        self.archive_dream_action = self.memory_menu.addAction("Archive Publish to Dream")
        self.archive_dream_action.setCheckable(True)
        self.archive_dream_action.setChecked(self.core.archive_publish_to_dream)
        self.archive_dream_action.toggled.connect(self.core.set_archive_publish_to_dream)
        self.archive_openbrain_action = self.memory_menu.addAction(
            "Archive Publish to OpenBrain"
        )
        self.archive_openbrain_action.setCheckable(True)
        self.archive_openbrain_action.setChecked(self.core.archive_publish_to_openbrain)
        self.archive_openbrain_action.toggled.connect(
            self.core.set_archive_publish_to_openbrain
        )
        self.memory_button.setMenu(self.memory_menu)
        top.addWidget(self.memory_button)

    def _on_provider_changed(self, index: int) -> None:
        key = self.provider_combo.itemData(index)
        if not key:
            return
        self.core.set_provider(key)

    def _run_dream_now(self) -> None:
        try:
            capsule = self.core.run_dream_pass()
        except Exception as exc:
            self.statusMessage.emit(f"Dream pass failed: {exc}")
            return
        self.viewer.setPlainText(str(capsule))
        self.statusMessage.emit("Dream pass completed.")

    def _open_memory_dialog(self) -> None:
        dialog = MemoryDialog(self.core, parent=self)
        dialog.exec()

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


class MemoryDialog(QDialog):
    """Qt-native viewer/editor for the ``ai_memory`` record (persona/style/rules).

    Presentation only: reads and writes through ``core.get_memory`` /
    ``core.set_memory`` (the same business APIs the Tk memory dialog uses).
    """

    def __init__(self, core, parent: QWidget | None = None):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("AI Memory")
        self.setMinimumWidth(420)

        mem = self.core.get_memory("global")
        form = QFormLayout(self)
        self.persona_edit = QLineEdit(str(mem.get("persona") or ""))
        self.style_edit = QLineEdit(str(mem.get("style") or ""))
        self.rules_edit = QPlainTextEdit()
        self.rules_edit.setPlainText("\n".join(mem.get("rules") or []))
        form.addRow("Persona", self.persona_edit)
        form.addRow("Style", self.style_edit)
        form.addRow("Rules (one per line)", self.rules_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        rules = [
            line.strip()
            for line in self.rules_edit.toPlainText().splitlines()
            if line.strip()
        ]
        self.core.set_memory(
            {
                "persona": self.persona_edit.text().strip(),
                "style": self.style_edit.text().strip(),
                "rules": rules,
            },
            "global",
        )
        self.accept()
