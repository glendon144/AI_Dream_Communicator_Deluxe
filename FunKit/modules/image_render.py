import base64, io, re
from typing import Optional, List

# Pillow is required for Tk rendering
try:
    from PIL import Image, ImageTk  # pillow
except Exception as e:
    raise RuntimeError("Pillow is required: pip install pillow") from e

# --- helpers ---------------------------------------------------------------

def _sniff_image_format(b: bytes) -> Optional[str]:
    if b.startswith(b"\x89PNG\r\n\x1a\n"): return "png"
    if b.startswith(b"\xff\xd8"): return "jpeg"
    if b.startswith(b"GIF87a") or b.startswith(b"GIF89a"): return "gif"
    if b.startswith(b"BM"): return "bmp"
    if b[0:4] == b"RIFF" and b[8:12] == b"WEBP": return "webp"
    return None

_DATA_URI_RE = re.compile(
    r"data:image/(png|jpe?g|gif|bmp|webp);base64,([A-Za-z0-9+/=\s]+)",
    re.IGNORECASE,
)

def extract_image_bytes_all(text: str) -> List[bytes]:
    """Return all decodable image blobs found in text (data URIs or raw b64)."""
    blobs: List[bytes] = []
    if not text:
        return blobs

    # 1) data: URIs (can be multiple)
    for m in _DATA_URI_RE.finditer(text):
        try:
            blobs.append(base64.b64decode(m.group(2)))
        except Exception:
            pass

    # 2) if no data: URIs, try whole text as raw base64
    if not blobs:
        cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", text)
        if cleaned:
            try:
                b = base64.b64decode(cleaned, validate=True)
                if _sniff_image_format(b):
                    blobs.append(b)
            except Exception:
                pass

    return blobs

# --- Tk rendering ----------------------------------------------------------

def show_images_in_text(text_widget, blobs: List[bytes], max_width: int | None = None):
    """Clear a Tkinter Text and embed one or more images, auto-resized to width."""
    if not blobs:
        return False

    # ensure widget has a width
    text_widget.update_idletasks()
    pane_w = text_widget.winfo_width() or 800
    if max_width is None:
        max_width = max(320, pane_w - 30)

    # clear and prepare
    text_widget.delete("1.0", "end")
    text_widget.tag_configure("center", justify="center")

    refs = getattr(text_widget, "_imgrefs", [])
    # make a new list; keep a reference on the widget to avoid GC
    refs = []
    for i, b in enumerate(blobs):
        im = Image.open(io.BytesIO(b))
        if im.width > max_width:
            h = int(im.height * (max_width / im.width))
            im = im.resize((max_width, h), Image.LANCZOS)

        photo = ImageTk.PhotoImage(im)
        refs.append(photo)

        # center with a blank line above & below
        text_widget.insert("end", "\n", "center")
        text_widget.image_create("end", image=photo)
        text_widget.insert("end", "\n", "center")

    text_widget._imgrefs = refs
    return True
