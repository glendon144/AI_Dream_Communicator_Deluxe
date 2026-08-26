"""Capture a Qt widget and prepare it for a context-capsule handoff.

The deliberately small API keeps screen capture separate from AI Navigator's
recovery UI.  Qt performs the capture and image encoding; no Pillow or ffmpeg
dependency is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt
from PySide6.QtGui import QGuiApplication, QImage


@dataclass(frozen=True)
class ScreenshotArtifact:
    """A saved browser-viewport image ready for clipboard transport."""

    path: Path
    width: int
    height: int


def grab_screenshot(
    widget,
    output_dir: Path,
    *,
    max_width: int = 1280,
    image_format: str = "PNG",
) -> ScreenshotArtifact:
    """Capture *widget*, save it locally, and return its image metadata.

    ``QWidget.grab`` is the simplest native route for a rendered
    ``QWebEngineView``.  Images wider than ``max_width`` are reduced while
    preserving their aspect ratio; smaller captures are left untouched.
    """

    if widget is None:
        raise ValueError("A Qt browser widget is required for screen capture.")

    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError("Qt returned an empty browser screenshot.")

    if max_width > 0 and pixmap.width() > max_width:
        pixmap = pixmap.scaledToWidth(
            max_width, Qt.TransformationMode.SmoothTransformation
        )

    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    suffix = image_format.lower().replace("jpeg", "jpg")
    path = output_dir / f"browser_view_{stamp}.{suffix}"

    if not pixmap.save(str(path), image_format):
        raise RuntimeError(f"Could not save browser screenshot to {path}")

    return ScreenshotArtifact(path=path, width=pixmap.width(), height=pixmap.height())


def append_screenshot_note(capsule: str, artifact: ScreenshotArtifact) -> str:
    """Add local provenance while explaining how the image is transported."""

    return (
        capsule.rstrip()
        + "\n\n**Browser viewport image**\n"
        + f"Captured at {artifact.width}Ã—{artifact.height}; local copy: "
        + f"`{artifact.path}`\n"
        + "The screenshot is also present as image data on the clipboard."
    )


def copy_capsule_with_image(capsule: str, artifact: ScreenshotArtifact) -> bool:
    """Put capsule text and PNG image data on the Qt clipboard together."""

    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False

    image = QImage(str(artifact.path))
    if image.isNull():
        raise RuntimeError(f"Could not load saved screenshot {artifact.path}")

    png_bytes = QByteArray()
    buffer = QBuffer(png_bytes)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(
        buffer, "PNG"
    ):
        raise RuntimeError("Could not encode browser screenshot for the clipboard.")

    mime = QMimeData()
    mime.setText(capsule)
    mime.setImageData(image)
    mime.setData("image/png", png_bytes)
    clipboard.setMimeData(mime)
    clipboard_mime = clipboard.mimeData()
    return bool(
        clipboard_mime
        and clipboard_mime.hasText()
        and clipboard_mime.hasImage()
        and clipboard_mime.hasFormat("image/png")
    )
