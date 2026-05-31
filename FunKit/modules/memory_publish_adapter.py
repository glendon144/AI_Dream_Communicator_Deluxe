from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

try:
    from dream import DreamProcessor
except ImportError:
    from PiKit.modules.dream import DreamProcessor

from dream_client import DreamClient
from openbrain_client import OpenBrainClient


@dataclass
class CanonicalCapsule:
    """Canonical in-memory capsule shape for FunKit-side memory publishing."""

    title: str
    capsule_type: str
    summary: str
    key_facts: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    recovery_hints: list[str] = field(default_factory=list)
    emotional_tone: str | None = None
    stylistic_profile: str | None = None
    confidence: float = 0.7
    scope: str = "private"
    trust_level: str = "local"
    retention: str = "normal"
    source_agent: str = "funkit"
    source_system: str = "funkit-ui"
    source_type: str = "archive"
    source_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any] = field(default_factory=dict)
    ttl_seconds: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DreamServerPublisher:
    """Maps canonical capsules into the Dream server `/store_capsule` schema."""

    def __init__(self, client: DreamClient) -> None:
        self.client = client

    def build_payload(self, capsule: CanonicalCapsule) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capsule_type": capsule.capsule_type,
            "summary": capsule.summary,
            "body": {
                "source_system": capsule.source_system,
                "source_references": self._source_references(capsule),
                "key_facts": capsule.key_facts,
                "themes": capsule.themes,
                "entities": capsule.entities,
                "relationships": capsule.relationships,
                "open_questions": capsule.open_questions,
                "contradictions": capsule.contradictions,
                "recovery_hints": capsule.recovery_hints,
                "emotional_tone": capsule.emotional_tone,
                "stylistic_profile": capsule.stylistic_profile,
                "domain_metadata": capsule.metadata,
            },
            "confidence": capsule.confidence,
            "retention": capsule.retention,
            "scope": capsule.scope,
            "trust_level": capsule.trust_level,
            "review_status": "unreviewed",
            "source_agent": capsule.source_agent,
            "source_type": capsule.source_type,
            "source_ref": capsule.source_ref,
            "lineage": capsule.lineage,
            "metadata": capsule.metadata,
        }
        if capsule.ttl_seconds is not None:
            payload["ttl_seconds"] = capsule.ttl_seconds
        return payload

    def publish(self, capsule: CanonicalCapsule) -> dict[str, Any]:
        return self.client.store_capsule_payload(self.build_payload(capsule))

    @staticmethod
    def _source_references(capsule: CanonicalCapsule) -> list[str]:
        if capsule.source_ref:
            return [capsule.source_ref]
        return []


class OpenBrainPublisher:
    """
    Publishes canonical capsules to OpenBrain through an explicit, swappable mapper.
    """

    def __init__(
        self,
        client: OpenBrainClient,
        mapper: Callable[[CanonicalCapsule], dict[str, Any]] | None = None,
    ) -> None:
        self.client = client
        self.mapper = mapper or self.default_mapper

    @staticmethod
    def default_mapper(capsule: CanonicalCapsule) -> dict[str, Any]:
        fact_lines = [f"- {fact}" for fact in capsule.key_facts if fact]
        content = "\n".join(part for part in [capsule.summary, *fact_lines] if part).strip()
        return {
            "title": capsule.title,
            "thought_type": "observation",
            "content": content,
            "metadata": {
                "themes": capsule.themes,
                "entities": capsule.entities,
                "source_agent": capsule.source_agent,
                "source_system": capsule.source_system,
                "source_type": capsule.source_type,
                "source_ref": capsule.source_ref,
                "lineage": capsule.lineage,
                "capsule_metadata": capsule.metadata,
            },
        }

    def publish(self, capsule: CanonicalCapsule) -> dict[str, Any]:
        return self.client.capture_thought(self.mapper(capsule))


class FunKitDreamAdapter:
    """Sits above `DreamProcessor` and optionally publishes derived capsules."""

    def __init__(
        self,
        processor: DreamProcessor,
        dream_publisher: DreamServerPublisher | None = None,
        openbrain_publisher: OpenBrainPublisher | None = None,
    ) -> None:
        self.processor = processor
        self.dream_publisher = dream_publisher
        self.openbrain_publisher = openbrain_publisher

    def note_archive_event(
        self,
        content: str,
        source_doc_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.processor.add_event(
            event_type="archive",
            content_snippet=content,
            source_doc_id=source_doc_id,
            metadata=metadata or {},
        )

    def build_capsule_from_latest(self, title: str = "FunKit archive capsule") -> CanonicalCapsule:
        capsule_text = self.processor.force_dream_pass()
        topics = self.processor.db.get_top_topics(limit=8)
        open_loops = self.processor.db.get_open_loops(limit=6)
        candidates = self.processor.db.get_recent_candidate_memories(limit=8)

        summary = self._derive_summary(capsule_text, title, candidates, open_loops, topics)
        key_facts = [str(row["object_text"]) for row in candidates if row["object_text"]]
        themes = [str(row["label"]) for row in topics if row["label"]]
        open_questions = [str(row["description"]) for row in open_loops if row["description"]]
        entities = self._derive_entities(candidates)
        relationships = self._derive_relationships(candidates)
        confidence = self._derive_confidence(candidates, open_loops)

        return CanonicalCapsule(
            title=title,
            capsule_type="dream",
            summary=summary,
            key_facts=key_facts[:12],
            themes=themes[:12],
            entities=entities[:12],
            relationships=relationships[:12],
            open_questions=open_questions[:8],
            contradictions=[],
            recovery_hints=open_questions[:8],
            confidence=confidence,
            scope="private",
            trust_level="local",
            retention="normal",
            source_agent="funkit",
            source_system="funkit-ui",
            source_type="archive",
            metadata={
                "capsule_text": capsule_text,
                "raw_local_capsule_text": capsule_text,
                "top_topics": themes[:12],
                "open_loops": open_questions[:8],
                "candidate_memory_count": len(candidates),
                "adapter": "FunKitDreamAdapter",
            },
            lineage={
                "derived_from": "local_dream_processor",
                "processor": type(self.processor).__name__,
                "build_method": "force_dream_pass",
            },
        )

    def publish_latest(
        self,
        title: str = "FunKit archive capsule",
        publish_to_dream: bool = False,
        publish_to_openbrain: bool = False,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        capsule = self.build_capsule_from_latest(title=title)
        capsule.ttl_seconds = ttl_seconds

        result: dict[str, Any] = {"capsule": capsule.to_dict()}

        if publish_to_dream and self.dream_publisher is not None:
            result["dream"] = self.dream_publisher.publish(capsule)

        if publish_to_openbrain and self.openbrain_publisher is not None:
            result["openbrain"] = self.openbrain_publisher.publish(capsule)

        return result

    @staticmethod
    def _derive_summary(
        capsule_text: str,
        title: str,
        candidates: list[Any],
        open_loops: list[Any],
        topics: list[Any],
    ) -> str:
        if candidates:
            first_fact = str(candidates[0]["object_text"]).strip()
            if first_fact:
                return first_fact[:160]
        if open_loops:
            first_loop = str(open_loops[0]["description"]).strip()
            if first_loop:
                return first_loop[:160]
        if topics:
            topic_names = ", ".join(str(row["label"]) for row in topics[:3] if row["label"])
            if topic_names:
                return f"{title}: {topic_names}"[:160]
        lines = [line.strip() for line in capsule_text.splitlines() if line.strip()]
        for line in lines:
            if line != "Dream Capsule" and not line.startswith("Generated:"):
                return line[:160]
        return title[:160]

    @staticmethod
    def _derive_entities(candidates: list[Any]) -> list[str]:
        entities: list[str] = []
        for row in candidates:
            subject = row["subject"]
            if subject and subject not in entities:
                entities.append(str(subject))
        return entities

    @staticmethod
    def _derive_relationships(candidates: list[Any]) -> list[dict[str, Any]]:
        relationships: list[dict[str, Any]] = []
        for row in candidates:
            subject = row["subject"]
            predicate = row["predicate"]
            object_text = row["object_text"]
            if not subject and not object_text:
                continue
            relationships.append(
                {
                    "subject": subject,
                    "predicate": predicate,
                    "object": object_text,
                    "memory_type": row["memory_type"],
                    "confidence": row["confidence"],
                    "salience": row["salience"],
                }
            )
        return relationships

    @staticmethod
    def _derive_confidence(candidates: list[Any], open_loops: list[Any]) -> float:
        values: list[float] = []
        for row in candidates:
            values.append(float(row["confidence"]))
        for row in open_loops:
            values.append(float(row["confidence"]))
        if not values:
            return 0.5
        return round(sum(values) / len(values), 3)
