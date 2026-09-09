"""Replaceable SequenceStore interface and local durable JSON store implementation.

Governed by ADR-014 and OS-004.
"""
from __future__ import annotations

import abc
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Union

from packages.catalog.identifiers import (
    EntityType,
    MAX_SEQUENCE,
    SequenceExhaustedError,
    SequencePersistenceError,
    SequenceStateError,
)

SCHEMA_VERSION = 1
REQUIRED_NAMESPACES = {e.value for e in EntityType}


def reject_json_constant(value: Any) -> None:
    """Reject NaN, Infinity, and -Infinity during JSON deserialization."""
    raise ValueError(f"Non-standard JSON numeric constant rejected: {value!r}")


def unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Strict dict builder rejecting duplicate JSON object keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key!r}")
        result[key] = value
    return result


class SequenceStore(abc.ABC):
    """Abstract interface for sequence persistence backends.

    Callers (such as IdentifierAllocator) depend only on this contract.
    Future implementations can connect to relational databases, Cloud Spanner,
    etc., without altering domain allocator logic.
    """

    @abc.abstractmethod
    def get_sequence(self, entity_type: EntityType) -> int:
        """Return the current sequence number for the given entity type (0 if empty).

        Must not advance or mutate sequence state.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_next_sequence(self, entity_type: EntityType) -> int:
        """Atomically increment and return the next sequence number for the given entity type.

        Must persist state durably before returning.
        Must raise SequenceExhaustedError if current sequence >= MAX_SEQUENCE.
        Must raise SequencePersistenceError if durable write fails.
        """
        raise NotImplementedError


class FileLock:
    """Cross-platform advisory file lock for local process coordination.

    Uses msvcrt on Windows and fcntl on POSIX systems.
    """

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    def acquire(self, timeout: float = 30.0, poll_interval: float = 0.005) -> None:
        start_time = time.monotonic()
        # Open lock file for writing/creation
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(
                str(self.lock_path),
                os.O_RDWR | os.O_CREAT,
                0o666,
            )
        except OSError as exc:
            raise SequencePersistenceError(f"Failed to open lock file {self.lock_path}: {exc}") from exc

        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    # LK_NBLCK: Non-blocking lock 1 byte at position 0
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    # Non-blocking exclusive lock
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Acquired lock successfully
                return
            except (BlockingIOError, OSError):
                if time.monotonic() - start_time >= timeout:
                    self.release()
                    raise SequencePersistenceError(
                        f"Timed out after {timeout}s acquiring lock on {self.lock_path}"
                    )
                time.sleep(poll_interval)

    def release(self) -> None:
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        os.lseek(self._fd, 0, os.SEEK_SET)
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None


class LocalJsonSequenceStore(SequenceStore):
    """Local durable sequence store using an atomic JSON file and file-level locking.

    Characteristics:
    - Standard library only (no external database server or cloud APIs)
    - Strict validation on read (fail-closed against corruption, type mismatch, out-of-range, extra keys)
    - Atomic write strategy (write temp file in same directory -> fsync -> atomic os.replace)
    - Re-entrant thread safety via threading.RLock
    - Local multi-process coordination via FileLock
    - Explicit non-goal: This store does NOT provide distributed multi-host atomicity.
    """

    def __init__(self, state_path: Union[str, Path]) -> None:
        self.state_path = Path(state_path).resolve()
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self.marker_path = self.state_path.with_name(self.state_path.name + ".initialized")
        self._thread_lock = threading.RLock()
        self._file_lock = FileLock(self.lock_path)

    @contextmanager
    def _locked(self) -> Generator[None, None, None]:
        """Acquire both thread lock and file lock for mutual exclusion."""
        with self._thread_lock:
            try:
                self._file_lock.acquire()
                yield
            finally:
                self._file_lock.release()

    def _initial_state(self) -> dict[str, Any]:
        """Initial pristine logical state for a fresh store."""
        return {
            "schema_version": SCHEMA_VERSION,
            "sequences": {
                EntityType.WORK.value: 0,
                EntityType.RECORDING.value: 0,
                EntityType.RELEASE.value: 0,
            },
        }

    def _validate_state(self, state: Any) -> dict[str, int]:
        """Strictly validate persisted dictionary structure and values.

        Fails closed on:
        - Non-dict root
        - Unsupported schema_version
        - Unknown top-level keys
        - Non-dict sequences container
        - Missing or extra namespace keys
        - Booleans masquerading as integers
        - Floats, strings, None, or negative numbers
        - Values exceeding MAX_SEQUENCE (999999)
        """
        if not isinstance(state, dict):
            raise SequenceStateError(f"State root must be a dict, got {type(state).__name__}")

        expected_root_keys = {"schema_version", "sequences"}
        if set(state.keys()) != expected_root_keys:
            raise SequenceStateError(
                f"State root keys mismatch. Expected {expected_root_keys}, got {set(state.keys())}"
            )

        schema_ver = state.get("schema_version")
        if not isinstance(schema_ver, int) or isinstance(schema_ver, bool):
            raise SequenceStateError(
                f"schema_version must be integer, got {type(schema_ver).__name__}"
            )
        if schema_ver != SCHEMA_VERSION:
            raise SequenceStateError(
                f"Unsupported schema_version: {schema_ver}. Expected {SCHEMA_VERSION}"
            )

        sequences = state.get("sequences")
        if not isinstance(sequences, dict):
            raise SequenceStateError(f"sequences must be a dict, got {type(sequences).__name__}")

        if set(sequences.keys()) != REQUIRED_NAMESPACES:
            raise SequenceStateError(
                f"sequences namespaces mismatch. Expected {REQUIRED_NAMESPACES}, got {set(sequences.keys())}"
            )

        validated: dict[str, int] = {}
        for ns, val in sequences.items():
            # In Python, bool is a subclass of int (isinstance(True, int) == True), so explicitly forbid bool!
            if isinstance(val, bool) or not isinstance(val, int):
                raise SequenceStateError(
                    f"Sequence for {ns} must be non-boolean integer, got {type(val).__name__}: {val!r}"
                )
            if val < 0:
                raise SequenceStateError(f"Sequence for {ns} cannot be negative: {val}")
            if val > MAX_SEQUENCE:
                raise SequenceStateError(
                    f"Sequence for {ns} exceeds maximum legal sequence {MAX_SEQUENCE}: {val}"
                )
            validated[ns] = val

        return validated

    def _read_state_under_lock(self) -> dict[str, int]:
        """Read one atomic snapshot; absence after initialization fails closed."""
        try:
            content = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            if self.marker_path.exists():
                raise SequenceStateError(
                    "Initialized sequence state is missing; operator recovery required"
                ) from exc
            return self._validate_state(self._initial_state())
        except (OSError, UnicodeError) as exc:
            raise SequenceStateError(f"Failed to read sequence store file {self.state_path}: {exc}") from exc

        try:
            raw_data = json.loads(
                content,
                parse_constant=reject_json_constant,
                object_pairs_hook=unique_json_pairs,
            )
        except Exception as exc:
            raise SequenceStateError(
                f"Malformed JSON in sequence store file {self.state_path}: {exc}"
            ) from exc

        return self._validate_state(raw_data)

    def _mark_initialized_under_lock(self) -> None:
        """Persist evidence before commit so state deletion cannot reset counters.

        A failed first commit may leave only this marker: recovery is deliberately
        required rather than guessing whether any allocation was committed.
        """
        if self.marker_path.exists():
            return
        try:
            with self.marker_path.open("xb") as marker:
                marker.write(b"initialized\n")
                marker.flush()
                os.fsync(marker.fileno())
        except OSError as exc:
            raise SequencePersistenceError("Failed to persist initialization marker") from exc

    def _write_state_under_lock(self, sequences: dict[str, int]) -> None:
        """Atomically persist validated sequences to disk.

        Steps:
        1. Build state document.
        2. Validate before writing.
        3. Write to temporary file in the same directory.
        4. Flush and fsync to ensure data reaches disk.
        5. Atomic rename (os.replace) over target path.
        """
        state_doc = {
            "schema_version": SCHEMA_VERSION,
            "sequences": sequences,
        }
        # Validate integrity prior to writing
        self._validate_state(state_doc)

        try:
            serialized = json.dumps(state_doc, indent=2) + "\n"
        except Exception as exc:
            raise SequencePersistenceError(f"Serialization failed: {exc}") from exc

        parent_dir = self.state_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        temp_file = None
        try:
            # Create temp file in same directory for atomic rename capability across filesystems
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent_dir,
                prefix=".ast_seq_tmp_",
                delete=False,
            ) as tf:
                temp_file = Path(tf.name)
                tf.write(serialized)
                tf.flush()
                os.fsync(tf.fileno())

            # Atomic replace
            os.replace(temp_file, self.state_path)
            temp_file = None
        except Exception as exc:
            if temp_file is not None and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise SequencePersistenceError(
                f"Failed to commit sequence state to {self.state_path}: {exc}"
            ) from exc

    def get_sequence(self, entity_type: EntityType) -> int:
        """Read an atomic snapshot without creating directories, locks, or state.

        The result is observational, not a reservation; a writer may advance it.
        """
        entity_type = EntityType.from_value(entity_type)
        state = self._read_state_under_lock()
        return state[entity_type.value]

    def get_next_sequence(self, entity_type: EntityType) -> int:
        """Advance sequence monotonically and persist state atomically."""
        entity_type = EntityType.from_value(entity_type)
        with self._locked():
            state = self._read_state_under_lock()
            curr = state[entity_type.value]
            if curr >= MAX_SEQUENCE:
                raise SequenceExhaustedError(
                    f"Namespace {entity_type.value} sequence exhausted (current={curr}, max={MAX_SEQUENCE})"
                )
            next_val = curr + 1
            state[entity_type.value] = next_val
            self._mark_initialized_under_lock()
            self._write_state_under_lock(state)
            return next_val
