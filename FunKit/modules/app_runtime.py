from __future__ import annotations

from pathlib import Path

from modules.ai_adapter import AIInterface
from modules.command_processor import CommandProcessor
from modules.document_store import DEFAULT_DB_PATH, DocumentStore
from modules.provider_registry import registry


def build_document_store(db_path: str | Path = DEFAULT_DB_PATH) -> DocumentStore:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return DocumentStore(path)


def build_ai(provider_key: str | None = None) -> AIInterface:
    key = provider_key or registry.read_selected()
    cfg = registry.get(key)
    return AIInterface(provider=cfg.key, default_model=cfg.model)


def build_processor(
    store: DocumentStore | None = None,
    provider_key: str | None = None,
) -> tuple[DocumentStore, AIInterface, CommandProcessor]:
    doc_store = store or build_document_store()
    ai = build_ai(provider_key=provider_key)
    processor = CommandProcessor(doc_store, ai)
    return doc_store, ai, processor
