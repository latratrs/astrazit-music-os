"""AstraZit Music OS - Catalog Package.

Provides canonical entity models, identifier allocation, and sequence storage.
Governed by ADR-012, ADR-014, and OS-004.
"""
from packages.catalog.identifiers import (
    AllocatorError,
    EntityType,
    IdentifierAllocator,
    InvalidEntityTypeError,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
    format_identifier,
    parse_identifier,
)
from packages.catalog.sequence_store import (
    LocalJsonSequenceStore,
    SequenceStore,
)

__all__ = [
    "AllocatorError",
    "EntityType",
    "IdentifierAllocator",
    "InvalidEntityTypeError",
    "LocalJsonSequenceStore",
    "SequenceExhaustedError",
    "SequencePersistenceError",
    "SequenceStateError",
    "SequenceStore",
    "format_identifier",
    "parse_identifier",
]
