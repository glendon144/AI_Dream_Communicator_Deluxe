"""
Compatibility shim for older imports.

Prefer importing from `memory_publish_adapter`.
"""

from memory_publish_adapter import (  # noqa: F401
    CanonicalCapsule,
    DreamServerPublisher,
    FunKitDreamAdapter,
    OpenBrainPublisher,
)
