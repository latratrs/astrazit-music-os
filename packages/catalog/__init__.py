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
from packages.catalog.local_repository import LocalJsonCatalogRepository
from packages.catalog.repository import (
    CatalogConflictError,
    CatalogError,
    CatalogIntegrityError,
    CatalogNotFoundError,
    CatalogPersistenceError,
    CatalogRepository,
    CatalogStateError,
    CatalogValidationError,
    create_with_allocated_id,
)
from packages.catalog.sequence_store import (
    LocalJsonSequenceStore,
    SequenceStore,
)
from packages.catalog.validation import (
    CatalogValidator,
    get_default_validator,
)

__all__ = [
    "AllocatorError",
    "CatalogConflictError",
    "CatalogError",
    "CatalogIntegrityError",
    "CatalogNotFoundError",
    "CatalogPersistenceError",
    "CatalogRepository",
    "CatalogStateError",
    "CatalogValidationError",
    "CatalogValidator",
    "EntityType",
    "IdentifierAllocator",
    "InvalidEntityTypeError",
    "LocalJsonCatalogRepository",
    "LocalJsonSequenceStore",
    "SequenceExhaustedError",
    "SequencePersistenceError",
    "SequenceStateError",
    "SequenceStore",
    "create_with_allocated_id",
    "format_identifier",
    "get_default_validator",
    "parse_identifier",
]
