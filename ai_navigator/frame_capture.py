"""Visual frame capture primitives for AI Dream Communicator Deluxe.

This module is deliberately agent-framework-agnostic. AI Navigator registers
named/numbered Qt widgets; Context Capsule generation and an MCP bridge can
then consume the same capture service.

Qt widget access must occur on the GUI thread. An MCP/background worker should
marshal its request to that thread before calling ``FrameCaptureService.capture``.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, QThread, Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class FrameCaptureError(RuntimeError):
    """Raised when a requested visual target cannot be captured."""


@dataclass(frozen=True)
class CaptureOptions:
    """Encoding and sizing controls for one screenshot."""

    max_width: int = 1024
    max_height: int = 1024
    image_format: str = "JPEG"
    quality: int = 80
    framebuffer: bool = False
    framebuffer_fallback: bool = True

    def normalized(self) -> "CaptureOptions":
        fmt = (self.image_format or "JPEG").upper()
        if fmt == "JPG":
            fmt = "JPEG"
        if fmt not in {"JPEG", "PNG", "WEBP"}:
            raise FrameCaptureError(f"Unsupported image format: {fmt}")
        return CaptureOptions(
            max_width=max(1, int(self.max_width)),
            max_height=max(1, int(self.max_height)),
            image_format=fmt,
            quality=max(0, min(100, int(self.quality))),
            framebuffer=bool(self.framebuffer),
            framebuffer_fallback=bool(self.framebuffer_fallback),
        )


@dataclass(frozen=True)
class CaptureResult:
    """One encoded screenshot plus Context Capsule/MCP-friendly metadata."""

    target_id: int
    target_name: str
    description: str
    captured_at: str
    width: int
    height: int
    image_format: str
    mime_type: str
    data: bytes
    capture_method: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def to_data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.to_base64()}"

    def as_dict(self, *, include_base64: bool = False) -> dict:
        payload = {
            "target_id": self.target_id,
            "target_name": self.target_name,
            "description": self.description,
            "captured_at": self.captured_at,
            "width": self.width,
            "height": self.height,
            "format": self.image_format,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "capture_method": self.capture_method,
        }
        if include_base64:
            payload["base64"] = self.to_base64()
        return payload

    def to_json(self, *, include_base64: bool = False, indent: int | None = 2) -> str:
        return json.dumps(
            self.as_dict(include_base64=include_base64),
            ensure_ascii=False,
            indent=indent,
        )

    def save(self, path: str | Path) -> Path:
        """Atomically save the already-encoded screenshot."""
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(self.data)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(destination)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return destination


@dataclass(frozen=True)
class _Target:
    target_id: int
    name: str
    description: str
    resolver: Callable[[], QWidget | None]


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _mime_type(image_format: str) -> str:
    return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[
        image_format
    ]


def _require_gui_thread() -> None:
    app = QApplication.instance()
    if app is None:
        raise FrameCaptureError("No QApplication exists; Qt cannot capture a widget.")
    if QThread.currentThread() is not app.thread():
        raise FrameCaptureError(
            "Frame capture must run on the Qt GUI thread; marshal MCP/background "
            "requests onto the GUI thread first."
        )


def _grab_widget(widget: QWidget) -> tuple[QPixmap, str]:
    pixmap = widget.grab()
    if pixmap.isNull():
        raise FrameCaptureError("Qt widget grab returned an empty pixmap.")
    return pixmap, "widget"


def _grab_framebuffer(widget: QWidget) -> tuple[QPixmap, str]:
    """Capture the onscreen pixels occupied by *widget*.

    This asks the window system for displayed pixels rather than asking the
    widget to render itself. Some Wayland/compositor configurations may deny
    this operation; callers may enable widget fallback.
    """
    window = widget.window()
    window_handle = window.windowHandle()
    screen = window_handle.screen() if window_handle is not None else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise FrameCaptureError("No screen is available for framebuffer capture.")

    origin: QPoint = widget.mapTo(window, QPoint(0, 0))
    pixmap = screen.grabWindow(
        int(window.winId()),
        origin.x(),
        origin.y(),
        max(1, widget.width()),
        max(1, widget.height()),
    )
    if pixmap.isNull():
        raise FrameCaptureError("Framebuffer capture returned an empty pixmap.")
    return pixmap, "framebuffer"


def _scale_pixmap(pixmap: QPixmap, options: CaptureOptions) -> QPixmap:
    if pixmap.width() <= options.max_width and pixmap.height() <= options.max_height:
        return pixmap
    return pixmap.scaled(
        options.max_width,
        options.max_height,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )


def _encode_pixmap(pixmap: QPixmap, options: CaptureOptions) -> bytes:
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise FrameCaptureError("Could not open the Qt image buffer.")
    try:
        ok = pixmap.save(buffer, options.image_format, options.quality)
    finally:
        buffer.close()
    if not ok:
        raise FrameCaptureError(
            f"Qt could not encode screenshot as {options.image_format}."
        )
    return bytes(byte_array)


def capture_widget(
    widget: QWidget, options: CaptureOptions | None = None
) -> tuple[bytes, int, int, str]:
    """Capture one QWidget and return bytes, width, height, and method."""
    _require_gui_thread()
    if widget is None:
        raise FrameCaptureError("Capture target resolved to None.")
    if not isinstance(widget, QWidget):
        raise FrameCaptureError(
            f"Capture target must be QWidget, not {type(widget).__name__}."
        )
    if widget.width() < 1 or widget.height() < 1:
        raise FrameCaptureError("Capture target has no visible geometry.")

    opts = (options or CaptureOptions()).normalized()
    if opts.framebuffer:
        try:
            pixmap, method = _grab_framebuffer(widget)
        except FrameCaptureError:
            if not opts.framebuffer_fallback:
                raise
            pixmap, method = _grab_widget(widget)
            method = "widget-fallback"
    else:
        pixmap, method = _grab_widget(widget)

    pixmap = _scale_pixmap(pixmap, opts)
    return _encode_pixmap(pixmap, opts), pixmap.width(), pixmap.height(), method


class FrameCaptureService:
    """Registry of stable visual targets such as browser/archive/memory/window."""

    def __init__(self, owner: QWidget | None = None):
        self._owner_ref = weakref.ref(owner) if owner is not None else None
        self._by_id: dict[int, _Target] = {}
        self._by_name: dict[str, _Target] = {}

    def register_target(
        self,
        target_id: int,
        name: str,
        widget_or_resolver: QWidget | Callable[[], QWidget | None],
        *,
        description: str = "",
        replace: bool = False,
    ) -> None:
        target_id = int(target_id)
        name = str(name).strip().lower()
        if not name:
            raise ValueError("Visual target name cannot be empty.")
        if not replace and (target_id in self._by_id or name in self._by_name):
            raise ValueError(
                f"Visual target id/name already registered: {target_id} / {name}"
            )

        if isinstance(widget_or_resolver, QWidget):
            resolver = weakref.ref(widget_or_resolver)
        elif callable(widget_or_resolver):
            resolver = widget_or_resolver
        else:
            raise TypeError("widget_or_resolver must be QWidget or callable.")

        target = _Target(target_id, name, description.strip(), resolver)
        old_by_id = self._by_id.get(target_id)
        if old_by_id is not None:
            self._by_name.pop(old_by_id.name, None)
        old_by_name = self._by_name.get(name)
        if old_by_name is not None:
            self._by_id.pop(old_by_name.target_id, None)
        self._by_id[target_id] = target
        self._by_name[name] = target

    def unregister_target(self, target: int | str) -> None:
        entry = self._resolve_entry(target)
        self._by_id.pop(entry.target_id, None)
        self._by_name.pop(entry.name, None)

    def list_targets(self) -> list[dict]:
        """Return JSON-safe target descriptions for UI or MCP discovery."""
        result: list[dict] = []
        for target_id in sorted(self._by_id):
            entry = self._by_id[target_id]
            widget = entry.resolver()
            result.append(
                {
                    "id": entry.target_id,
                    "name": entry.name,
                    "description": entry.description,
                    "available": widget is not None,
                    "visible": bool(widget and widget.isVisible()),
                    "width": widget.width() if widget else 0,
                    "height": widget.height() if widget else 0,
                }
            )
        return result

    def capture(
        self, target: int | str, options: CaptureOptions | None = None
    ) -> CaptureResult:
        entry = self._resolve_entry(target)
        widget = entry.resolver()
        if widget is None:
            raise FrameCaptureError(
                f"Visual target {entry.target_id}:{entry.name} is unavailable."
            )

        opts = (options or CaptureOptions()).normalized()
        data, width, height, method = capture_widget(widget, opts)
        return CaptureResult(
            target_id=entry.target_id,
            target_name=entry.name,
            description=entry.description,
            captured_at=_utc_timestamp(),
            width=width,
            height=height,
            image_format=opts.image_format,
            mime_type=_mime_type(opts.image_format),
            data=data,
            capture_method=method,
        )

    def capture_to_file(
        self,
        target: int | str,
        directory: str | Path,
        options: CaptureOptions | None = None,
        *,
        basename: str | None = None,
    ) -> tuple[CaptureResult, Path]:
        result = self.capture(target, options)
        extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[
            result.image_format
        ]
        safe_timestamp = (
            result.captured_at.replace(":", "").replace("-", "").replace(".", "")
        )
        filename = basename or f"{result.target_name}-{safe_timestamp}{extension}"
        if basename is not None and not Path(filename).suffix:
            filename += extension
        path = Path(directory).expanduser() / filename
        return result, result.save(path)

    def _resolve_entry(self, target: int | str) -> _Target:
        if isinstance(target, int):
            entry = self._by_id.get(target)
        else:
            text = str(target).strip().lower()
            if text.isdecimal() or (text.startswith("-") and text[1:].isdecimal()):
                entry = self._by_id.get(int(text))
            else:
                entry = self._by_name.get(text)
        if entry is None:
            available = ", ".join(
                f"{item.target_id}:{item.name}"
                for item in sorted(self._by_id.values(), key=lambda x: x.target_id)
            )
            raise FrameCaptureError(
                f"Unknown visual target {target!r}. Available targets: {available}"
            )
        return entry


def suggested_target_map() -> tuple[tuple[int, str, str], ...]:
    """Suggested stable IDs; AI Navigator decides which widgets implement them."""
    return (
        (0, "browser", "Current browser viewport"),
        (1, "archive", "Archive/results pane"),
        (2, "memory", "Memory pane"),
        (3, "gmail", "Gmail pane"),
        (4, "webmcp", "WebMCP actions pane"),
        (5, "pikit", "PiKit pane"),
        (6, "funkit", "FunKit pane"),
        (9, "window", "Full AI Dream Communicator Deluxe window"),
    )
