# modules/exporter.py
import os
import json
import base64
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---- Helpers ----------------------------------------------------------------

_IMAGE_HINT_KEYS = {
    "image",
    "thumbnail",
    "preview",
    "png",
    "jpeg",
    "jpg",
    "gif",
    "bmp",
    "webp",
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _guess_image_mime(name: str) -> str:
    n = (name or "").lower()
    if n.endswith(".png"):
        return "image/png"
    if n.endswith(".jpg") or n.endswith(".jpeg"):
        return "image/jpeg"
    if n.endswith(".gif"):
        return "image/gif"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith(".bmp"):
        return "image/bmp"
    return "image/png"


def _looks_like_image_key(key: str) -> bool:
    k = (key or "").lower()
    return any(h in k for h in _IMAGE_HINT_KEYS)


def _sanitize_for_json(obj: Any) -> Any:
    """
    Recursively convert to JSON-safe forms:
      - bytes -> base64 string
      - Path -> str
      - set/tuple -> list
      - dict/list -> recurse
      - primitives unchanged
    """
    if isinstance(obj, bytes):
        return _b64(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(x) for x in obj]
    return obj


def _lift_inline_images(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Promote likely image fields (bytes or base64 strings) into doc['images']
    so the Flask server can render them. Original fields are left in place,
    but bytes will become base64 via _sanitize_for_json.
    """
    if not isinstance(doc, dict):
        return doc

    images: List[Dict[str, Any]] = list(doc.get("images") or [])
    for k, v in list(doc.items()):
        if not _looks_like_image_key(k):
            continue
        # bytes -> base64; str assumed already base64 or data URL (we don't validate)
        if isinstance(v, bytes):
            b64 = _b64(v)
        elif isinstance(v, str) and v:
            b64 = v
        else:
            continue
        images.append({"mime": _guess_image_mime(k), "data_base64": b64, "alt": k})

    if images:
        doc["images"] = images
    return doc


# ---- Main export -------------------------------------------------------------


def export_documents(doc_store, output_dir: str = "exported_docs"):
    """
    Export each document as JSON, safely handling bytes and adding images.
    """
    os.makedirs(output_dir, exist_ok=True)
    index = doc_store.get_document_index()

    for rec in index:
        doc_id = rec["id"]
        row = doc_store.get_document(doc_id)
        doc = dict(row)  # sqlite3.Row -> dict

        # 1) Lift likely image fields to images[]
        doc = _lift_inline_images(doc)
        # 2) Sanitize everything (bytes -> base64, etc.)
        safe_doc = _sanitize_for_json(doc)

        out_path = Path(output_dir) / f"{doc_id}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(safe_doc, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(index)} documents to '{output_dir}'")
