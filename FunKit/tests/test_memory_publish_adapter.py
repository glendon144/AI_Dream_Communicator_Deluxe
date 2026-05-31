from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import Mock


MODULES_DIR = Path("/home/gross/src/050526/funkit/modules")
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))


def _load_adapter_module():
    dream_module = types.ModuleType("dream")

    class DreamProcessor:
        pass

    dream_module.DreamProcessor = DreamProcessor
    sys.modules["dream"] = dream_module

    dream_client_module = types.ModuleType("dream_client")

    class DreamClient:
        pass

    dream_client_module.DreamClient = DreamClient
    sys.modules["dream_client"] = dream_client_module

    openbrain_client_module = types.ModuleType("openbrain_client")

    class OpenBrainClient:
        pass

    openbrain_client_module.OpenBrainClient = OpenBrainClient
    sys.modules["openbrain_client"] = openbrain_client_module

    sys.modules.pop("memory_publish_adapter", None)
    return importlib.import_module("memory_publish_adapter")


adapter_module = _load_adapter_module()
CanonicalCapsule = adapter_module.CanonicalCapsule
DreamServerPublisher = adapter_module.DreamServerPublisher
OpenBrainPublisher = adapter_module.OpenBrainPublisher
FunKitDreamAdapter = adapter_module.FunKitDreamAdapter


def make_capsule(**overrides):
    base = {
        "title": "Archive note",
        "capsule_type": "dream",
        "summary": "Session summary",
        "key_facts": ["Fact one", "Fact two"],
        "themes": ["memory", "archive"],
        "entities": ["FunKit", "Dream"],
        "relationships": [{"subject": "FunKit", "predicate": "uses", "object": "Dream"}],
        "open_questions": ["What should be retained?"],
        "contradictions": ["None yet"],
        "recovery_hints": ["Check archive action"],
        "emotional_tone": "neutral",
        "stylistic_profile": "concise",
        "confidence": 0.82,
        "scope": "private",
        "trust_level": "local",
        "retention": "normal",
        "source_agent": "funkit",
        "source_system": "funkit-ui",
        "source_type": "archive",
        "source_ref": "doc-42",
        "metadata": {"custom": "value"},
        "lineage": {"derived_from": "local_dream_processor"},
    }
    base.update(overrides)
    return CanonicalCapsule(**base)


def make_processor():
    processor = Mock()
    processor.force_dream_pass.return_value = "Dream Capsule\nGenerated: now\n\nCandidate memories:\n- fact"
    processor.db.get_top_topics.return_value = [
        {"label": "memory"},
        {"label": "archive"},
    ]
    processor.db.get_open_loops.return_value = [
        {"description": "Follow up on archive", "confidence": 0.7},
    ]
    processor.db.get_recent_candidate_memories.return_value = [
        {
            "object_text": "Captured archive event",
            "subject": "FunKit",
            "predicate": "captured",
            "memory_type": "event",
            "confidence": 0.9,
            "salience": 0.8,
        },
        {
            "object_text": "Dream adapter prepared capsule",
            "subject": "Dream adapter",
            "predicate": "prepared",
            "memory_type": "fact",
            "confidence": 0.8,
            "salience": 0.7,
        },
    ]
    return processor


def test_canonical_capsule_defaults_and_ttl():
    capsule = CanonicalCapsule(title="T", capsule_type="dream", summary="S", ttl_seconds=60)

    assert capsule.key_facts == []
    assert capsule.themes == []
    assert capsule.metadata == {}
    assert capsule.lineage == {}
    assert capsule.ttl_seconds == 60


def test_dream_server_publisher_includes_ttl_when_present():
    client = Mock()
    client.store_capsule_payload.return_value = {"ok": True}
    publisher = DreamServerPublisher(client)
    capsule = make_capsule(ttl_seconds=300)

    result = publisher.publish(capsule)

    assert result == {"ok": True}
    payload = client.store_capsule_payload.call_args.args[0]
    assert payload["summary"] == "Session summary"
    assert payload["body"]["key_facts"] == ["Fact one", "Fact two"]
    assert payload["body"]["themes"] == ["memory", "archive"]
    assert payload["body"]["entities"] == ["FunKit", "Dream"]
    assert payload["body"]["relationships"] == [
        {"subject": "FunKit", "predicate": "uses", "object": "Dream"}
    ]
    assert payload["metadata"] == {"custom": "value"}
    assert payload["lineage"] == {"derived_from": "local_dream_processor"}
    assert payload["ttl_seconds"] == 300


def test_dream_server_publisher_omits_ttl_when_none():
    client = Mock()
    publisher = DreamServerPublisher(client)
    capsule = make_capsule(ttl_seconds=None)

    publisher.publish(capsule)

    payload = client.store_capsule_payload.call_args.args[0]
    assert "ttl_seconds" not in payload


def test_openbrain_default_mapper_shape():
    client = Mock()
    publisher = OpenBrainPublisher(client)
    capsule = make_capsule()

    args = publisher.default_mapper(capsule)

    assert args["title"] == "Archive note"
    assert args["thought_type"] == "observation"
    assert "Session summary" in args["content"]
    assert "- Fact one" in args["content"]
    assert "- Fact two" in args["content"]
    assert args["metadata"]["themes"] == ["memory", "archive"]
    assert args["metadata"]["entities"] == ["FunKit", "Dream"]
    assert args["metadata"]["source_agent"] == "funkit"
    assert args["metadata"]["source_system"] == "funkit-ui"
    assert args["metadata"]["source_type"] == "archive"
    assert args["metadata"]["source_ref"] == "doc-42"
    assert args["metadata"]["lineage"] == {"derived_from": "local_dream_processor"}
    assert args["metadata"]["capsule_metadata"] == {"custom": "value"}


def test_note_archive_event_forwards_to_processor():
    processor = Mock()
    adapter = FunKitDreamAdapter(processor=processor)

    adapter.note_archive_event("Archived content", source_doc_id=12, metadata={"x": 1})

    processor.add_event.assert_called_once_with(
        event_type="archive",
        content_snippet="Archived content",
        source_doc_id=12,
        metadata={"x": 1},
    )


def test_build_capsule_from_latest_uses_processor_outputs():
    processor = make_processor()
    adapter = FunKitDreamAdapter(processor=processor)

    capsule = adapter.build_capsule_from_latest(title="FunKit archive capsule")

    processor.force_dream_pass.assert_called_once_with()
    processor.db.get_top_topics.assert_called_once_with(limit=8)
    processor.db.get_open_loops.assert_called_once_with(limit=6)
    processor.db.get_recent_candidate_memories.assert_called_once_with(limit=8)
    assert isinstance(capsule, CanonicalCapsule)
    assert capsule.metadata["capsule_text"].startswith("Dream Capsule")
    assert capsule.themes == ["memory", "archive"]
    assert capsule.open_questions == ["Follow up on archive"]
    assert capsule.key_facts == [
        "Captured archive event",
        "Dream adapter prepared capsule",
    ]
    assert capsule.lineage["derived_from"] == "local_dream_processor"


def test_publish_latest_publishes_to_requested_targets_and_passes_ttl():
    processor = make_processor()
    dream_publisher = Mock()
    dream_publisher.publish.return_value = {"dream": "ok"}
    openbrain_publisher = Mock()
    openbrain_publisher.publish.return_value = {"openbrain": "ok"}
    adapter = FunKitDreamAdapter(
        processor=processor,
        dream_publisher=dream_publisher,
        openbrain_publisher=openbrain_publisher,
    )

    dream_only = adapter.publish_latest(
        title="Dream only",
        publish_to_dream=True,
        publish_to_openbrain=False,
        ttl_seconds=120,
    )
    openbrain_only = adapter.publish_latest(
        title="OpenBrain only",
        publish_to_dream=False,
        publish_to_openbrain=True,
    )
    both = adapter.publish_latest(
        title="Both",
        publish_to_dream=True,
        publish_to_openbrain=True,
    )
    neither = adapter.publish_latest(
        title="Neither",
        publish_to_dream=False,
        publish_to_openbrain=False,
    )

    assert dream_only["dream"] == {"dream": "ok"}
    assert "openbrain" not in dream_only
    assert openbrain_only["openbrain"] == {"openbrain": "ok"}
    assert "dream" not in openbrain_only
    assert both["dream"] == {"dream": "ok"}
    assert both["openbrain"] == {"openbrain": "ok"}
    assert set(neither) == {"capsule"}

    first_dream_capsule = dream_publisher.publish.call_args_list[0].args[0]
    assert first_dream_capsule.ttl_seconds == 120
    assert dream_publisher.publish.call_count == 2
    assert openbrain_publisher.publish.call_count == 2
