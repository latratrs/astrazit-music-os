"""Canonical CatalogRepository contract and domain exceptions.

Governed by ADR-001, ADR-003, ADR-012, and OS-005.
"""
from __future__ import annotations

import abc
import copy
from typing import Any, Callable, Optional, Union

from packages.catalog.identifiers import (
    EntityType,
    IdentifierAllocator,
)


class CatalogError(Exception):
    """Base exception for all catalog repository errors."""


class CatalogValidationError(CatalogError):
    """Raised when a canonical record fails schema validation or entity type invariants."""


class CatalogNotFoundError(CatalogError):
    """Raised when a requested canonical entity ID does not exist in the repository."""


class CatalogConflictError(CatalogError):
    """Raised when attempting to create a canonical entity whose ID already exists."""


class CatalogIntegrityError(CatalogError):
    """Raised when referential integrity between catalog entities is violated."""


class CatalogStateError(CatalogError):
    """Raised when repository storage is corrupted, malformed, or untrusted."""


class CatalogPersistenceError(CatalogError):
    """Raised when a durable write or lock acquisition fails."""


class CatalogRepository(abc.ABC):
    """Abstract domain repository interface for AstraZit Music OS catalog entities.

    Callers interact exclusively through this interface, keeping the persistence
    backend completely replaceable without altering domain callers.
    """

    @abc.abstractmethod
    def create(self, entity_type: Union[EntityType, str], record: dict[str, Any]) -> dict[str, Any]:
        """Validate, verify referential integrity, and persist a new canonical record.

        Args:
            entity_type: WORK, RECORDING, or RELEASE.
            record: Complete canonical record dictionary matching JSON Schema Draft 2020-12.

        Returns:
            A deep copy of the successfully persisted canonical record.

        Raises:
            CatalogValidationError: If entity type is invalid, schema fails, or ID mismatch.
            CatalogConflictError: If the canonical AST ID already exists.
            CatalogIntegrityError: If referenced entities do not exist or have wrong type.
            CatalogPersistenceError: If durable storage write fails.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, entity_type: Union[EntityType, str], ast_id: str) -> dict[str, Any]:
        """Retrieve a canonical record by AST identity.

        Args:
            entity_type: WORK, RECORDING, or RELEASE.
            ast_id: Canonical AST identifier (e.g. AST-WRK-000001).

        Returns:
            A deep copy of the canonical record. Mutating this copy does not mutate storage.

        Raises:
            CatalogValidationError: If entity type or ast_id is invalid.
            CatalogNotFoundError: If the record does not exist.
            CatalogStateError: If stored record is corrupted or malformed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def update(self, entity_type: Union[EntityType, str], ast_id: str, record: dict[str, Any]) -> dict[str, Any]:
        """Validate, verify immutable identity, check referential integrity, and replace an existing record.

        Args:
            entity_type: WORK, RECORDING, or RELEASE.
            ast_id: Canonical AST identifier to update.
            record: Proposed full canonical replacement record.

        Returns:
            A deep copy of the successfully updated canonical record.

        Raises:
            CatalogValidationError: If schema fails or proposed record alters ast_id.
            CatalogNotFoundError: If the record does not currently exist.
            CatalogIntegrityError: If referenced entities do not exist or have wrong type.
            CatalogPersistenceError: If durable storage write fails.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def exists(self, entity_type: Union[EntityType, str], ast_id: str) -> bool:
        """Check if a canonical entity ID exists in the repository without mutating state.

        Args:
            entity_type: WORK, RECORDING, or RELEASE.
            ast_id: Canonical AST identifier.

        Returns:
            True if present and valid; False if not found.

        Raises:
            CatalogValidationError: If entity type or ast_id is invalid.
            CatalogStateError: If stored record is corrupted.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def list_ids(self, entity_type: Union[EntityType, str]) -> list[str]:
        """Return a sorted list of canonical AST IDs for the given entity type.

        Args:
            entity_type: WORK, RECORDING, or RELEASE.

        Returns:
            Deterministically sorted list of valid AST identifiers.

        Raises:
            CatalogValidationError: If entity type is invalid.
            CatalogStateError: If storage corruption or unparseable record is encountered.
        """
        raise NotImplementedError


def create_with_allocated_id(
    allocator: IdentifierAllocator,
    repository: CatalogRepository,
    entity_type: Union[EntityType, str],
    record_factory: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Orchestration helper separating identity allocation from record persistence.

    1. Allocates the next AST ID from allocator.
    2. Passes the allocated ID to record_factory to construct the record.
    3. Persists the record via repository.create().

    If record_factory or repository.create fails, the allocated ID is consumed/burned,
    preserving non-recycling invariants.
    """
    resolved_type = EntityType.from_value(entity_type)
    ast_id = allocator.allocate(resolved_type)
    record = record_factory(ast_id)
    return repository.create(resolved_type, record)
