"""AST Identifier Allocator & Canonical Namespace Definitions.

Governed by ADR-012, ADR-014, and OS-004.
"""
from __future__ import annotations

import enum
import re
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from packages.catalog.sequence_store import SequenceStore

# Canonical limits
MIN_SEQUENCE = 1
MAX_SEQUENCE = 999999
SEQUENCE_DIGITS = 6


class EntityType(enum.Enum):
    """Canonical AstraZit Music OS entity types eligible for AST identification."""
    WORK = "WORK"
    RECORDING = "RECORDING"
    RELEASE = "RELEASE"

    @classmethod
    def from_value(cls, value: Union[EntityType, str]) -> EntityType:
        """Parse an EntityType from an instance or string safely."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            try:
                return cls[normalized]
            except KeyError:
                raise InvalidEntityTypeError(
                    f"Unknown entity type: {value!r}. Must be one of {[e.value for e in cls]}"
                )
        raise InvalidEntityTypeError(
            f"Invalid entity type specifier of type {type(value).__name__}: {value!r}"
        )


ENTITY_PREFIXES = {
    EntityType.WORK: "AST-WRK-",
    EntityType.RECORDING: "AST-REC-",
    EntityType.RELEASE: "AST-REL-",
}

# Strict regex patterns for validation
ID_PATTERNS = {
    EntityType.WORK: re.compile(r"^AST-WRK-[0-9]{6}$"),
    EntityType.RECORDING: re.compile(r"^AST-REC-[0-9]{6}$"),
    EntityType.RELEASE: re.compile(r"^AST-REL-[0-9]{6}$"),
}


class AllocatorError(Exception):
    """Base exception for all identifier allocator errors."""


class InvalidEntityTypeError(AllocatorError):
    """Raised when an unknown or invalid entity type is provided."""


class SequenceExhaustedError(AllocatorError):
    """Raised when a namespace sequence reaches its maximum capacity (999999)."""


class SequenceStateError(AllocatorError):
    """Raised when sequence store state is corrupted, malformed, or invalid."""


class SequencePersistenceError(AllocatorError):
    """Raised when persisting allocation state fails."""


def format_identifier(entity_type: EntityType, sequence: int) -> str:
    """Format an entity type and numeric sequence into a canonical AST identifier.

    Validates that the sequence is strictly within the closed legal range [1, 999999].
    """
    if not isinstance(sequence, int) or isinstance(sequence, bool):
        raise SequenceStateError(
            f"Sequence must be a non-boolean integer, got {type(sequence).__name__}: {sequence!r}"
        )
    if sequence < MIN_SEQUENCE or sequence > MAX_SEQUENCE:
        raise SequenceStateError(
            f"Sequence {sequence} outside valid range [{MIN_SEQUENCE}, {MAX_SEQUENCE}]"
        )
    prefix = ENTITY_PREFIXES[entity_type]
    identifier = f"{prefix}{sequence:0{SEQUENCE_DIGITS}d}"
    if not ID_PATTERNS[entity_type].fullmatch(identifier):
        raise SequenceStateError(f"Generated identifier {identifier!r} failed format check")
    return identifier


def parse_identifier(identifier: str) -> tuple[EntityType, int]:
    """Parse and validate a canonical AST identifier into (EntityType, sequence).

    Fails closed if the identifier format is invalid or out of range.
    """
    if not isinstance(identifier, str):
        raise AllocatorError(f"Identifier must be a string, got {type(identifier).__name__}")
    
    for entity_type, pattern in ID_PATTERNS.items():
        if pattern.fullmatch(identifier):
            prefix = ENTITY_PREFIXES[entity_type]
            num_str = identifier[len(prefix):]
            seq = int(num_str)
            if seq < MIN_SEQUENCE or seq > MAX_SEQUENCE:
                raise AllocatorError(f"Sequence {seq} in identifier {identifier!r} out of bounds")
            return entity_type, seq
            
    raise AllocatorError(f"Invalid canonical identifier format: {identifier!r}")


class IdentifierAllocator:
    """Deterministic AST internal identifier allocator service.

    Enforces:
    - Immutability and monotonic advancement
    - Independence across WORK, RECORDING, RELEASE namespaces
    - Fail-closed exhaustion at 999999
    - Decoupling from external platform identifiers (ISRC, ISWC, UPC, etc.)
    - Pure domain logic delegating persistence to a pluggable SequenceStore
    """

    def __init__(self, store: SequenceStore) -> None:
        self._store = store

    def allocate(self, entity_type: Union[EntityType, str]) -> str:
        """Atomically allocate the next canonical identifier for the specified entity type.

        Returns only after the store commits. Failure may burn a sequence if
        commit succeeded before the error; callers must never restore old state.
        """
        etype = EntityType.from_value(entity_type)
        next_seq = self._store.get_next_sequence(etype)
        return format_identifier(etype, next_seq)

    def peek_next(self, entity_type: Union[EntityType, str]) -> str:
        """Inspect the next identifier that would be allocated without advancing sequence state.

        Read-only inspection: does not consume or mutate state.
        """
        etype = EntityType.from_value(entity_type)
        curr = self._store.get_sequence(etype)
        next_seq = curr + 1
        if next_seq > MAX_SEQUENCE:
            raise SequenceExhaustedError(
                f"Namespace {etype.value} is exhausted (current={curr}, max={MAX_SEQUENCE})"
            )
        return format_identifier(etype, next_seq)

    def current_sequence(self, entity_type: Union[EntityType, str]) -> int:
        """Inspect the current highest allocated sequence number for the entity type.

        Returns 0 if no allocations have occurred yet in the namespace.
        Read-only inspection: does not consume or mutate state.
        """
        etype = EntityType.from_value(entity_type)
        return self._store.get_sequence(etype)
