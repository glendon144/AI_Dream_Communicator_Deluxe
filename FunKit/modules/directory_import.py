
#!/usr/bin/env python3
# modules/directory_import.py — unified directory importer
# - API: import_text_files_from_directory(directory, doc_store, skip_existing=True)
# - Empty files count as text
# - Text detection: extension/MIME + quick binary sniff
# - UTF-8 decode with errors="replace"
# - Non-recursive; easy to make recursive if desired

from __future__ import annotations
from pathlib import Path
import mimetypes
import os

TEXT_EXTS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".ini", ".cfg", ".toml",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp", ".sh", ".bat",
}

def _is_probably_text(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    if size == 0:
        return True
    if path.suffix.lower() in TEXT_EXTS:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    if mime and mime.startswith("text/"):
        return True
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return False
        high = sum(b >= 0x80 for b in chunk)
        return high / max(1, len(chunk)) < 0.3
    except Exception:
        return False

def import_text_files_from_directory(directory: str | os.PathLike[str], doc_store, skip_existing: bool = True):
    """Import text-like files from a directory into the document store.
    Args:
        directory (str | Path): Path to directory (non-recursive).
        doc_store: DocumentStore with .has_title(title) and .add_document(title, body)
        skip_existing (bool): Skip files whose titles already exist.
    Returns:
        (imported_count, skipped_count)
    """
    imported = skipped = 0
    directory = Path(directory)
    if not directory.exists() or not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    for p in sorted(directory.iterdir()):
        if not p.is_file():
            continue
        if not _is_probably_text(p):
            continue

        title = p.stem
        if skip_existing and hasattr(doc_store, "has_title") and doc_store.has_title(title):
            skipped += 1
            continue

        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"[WARN] Skipped {p}: {e}")
            skipped += 1
            continue

        try:
            if hasattr(doc_store, "add_document"):
                doc_store.add_document(title, body)
                imported += 1
            else:
                print(f"[WARN] doc_store missing add_document(title, body); cannot import {p}")
                skipped += 1
        except Exception as e:
            print(f"[WARN] Skipped {p}: {e}")
            skipped += 1

    return imported, skipped
