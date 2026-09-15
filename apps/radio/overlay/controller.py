"""
apps/radio/overlay/controller.py
Overlay State Controller.
Manages metadata state, transitions (fade-out -> swap -> fade-in),
atomic writes, and failure isolation.
"""
from __future__ import annotations
import os
import time
import json
import threading
import queue
from enum import Enum
from typing import Dict, Any, Optional, Callable

from .sanitizer import normalize_metadata
from .renderer import render_overlay_bytes
from .atomic_writer import atomic_write_png

FADE_DURATION_DEFAULT = 1.5
FPS_STEPS_DEFAULT = 15  # 15 steps per second during fade = ~22 frames per 1.5s fade


class TransitionState(str, Enum):
    IDLE = "IDLE"
    VISIBLE = "VISIBLE"
    FADING_OUT = "FADING_OUT"
    SWAP = "SWAP"
    FADING_IN = "FADING_IN"


class OverlayController:
    """
    Controls now-playing overlay lifecycle:
    - Bounded queue / single pending slot coalescing for rapid bursts (latest valid metadata wins).
    - Manages smooth 1.5s fade-out -> swap -> 1.5s fade-in transition.
    - Explicit state machine: IDLE -> FADING_IN -> VISIBLE -> FADING_OUT -> SWAP -> FADING_IN -> VISIBLE.
    - Emits atomic RGBA PNG frames to the target file and optional frame callback (for pipe streaming).
    - Guarantees fail-open stability: malformed input never crashes worker.
    """
    def __init__(
        self,
        target_png_path: Optional[str] = None,
        fade_duration: float = FADE_DURATION_DEFAULT,
        steps_per_sec: int = FPS_STEPS_DEFAULT,
        frame_callback: Optional[Callable[[bytes, Dict[str, str], float], None]] = None,
    ):
        self.target_png_path = os.path.abspath(target_png_path) if target_png_path else None
        self.fade_duration = max(0.01, fade_duration)
        self.steps_per_sec = max(2, steps_per_sec)
        self.frame_callback = frame_callback

        self.current_metadata: Optional[Dict[str, str]] = None
        self.last_known_good_metadata: Optional[Dict[str, str]] = None
        self._pending_metadata: Optional[Dict[str, str]] = None

        self._state: TransitionState = TransitionState.IDLE
        self._current_opacity: float = 0.0

        # Event to wake worker thread immediately on new submission
        self._wake_event = threading.Event()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Metrics & counters
        self.total_submitted: int = 0
        self.total_coalesced: int = 0
        self.total_transitions_completed: int = 0

    @property
    def state(self) -> TransitionState:
        with self._lock:
            return self._state

    @property
    def current_opacity(self) -> float:
        with self._lock:
            return self._current_opacity

    @property
    def pending_metadata(self) -> Optional[Dict[str, str]]:
        with self._lock:
            return self._pending_metadata

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(target=self._run_loop, daemon=True)
            self._worker_thread.start()

    def stop(self, timeout: float = 3.0):
        with self._lock:
            self._running = False
            self._wake_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)

    def submit_metadata(self, metadata: Any) -> bool:
        """
        Thread-safe submission of new metadata.
        Normalizes input and validates payload.
        Implements latest-valid-metadata-wins by overwriting pending slot.
        """
        try:
            normalized = normalize_metadata(metadata)
        except Exception:
            return False

        with self._lock:
            self.total_submitted += 1

            # If identical to currently displayed metadata and no different pending state, ignore
            if self._pending_metadata is None and self.current_metadata == normalized:
                return True

            # If already have a pending item that is identical to this new one, ignore
            if self._pending_metadata == normalized:
                return True

            if self._pending_metadata is not None:
                self.total_coalesced += 1

            # Latest valid metadata wins: overwrite single pending slot (bounded queue size <= 1)
            self._pending_metadata = normalized
            self._wake_event.set()
            return True

    def _emit_frame(self, metadata: Dict[str, str], opacity: float) -> bool:
        with self._lock:
            self._current_opacity = opacity
        try:
            png_bytes = render_overlay_bytes(metadata, opacity=opacity)
        except Exception:
            return False

        written = True
        if self.target_png_path:
            try:
                # During animation frames, fsync=False is used so high-frequency steps do not stall on OS flush
                written = atomic_write_png(self.target_png_path, png_bytes, sync_to_disk=False)
            except Exception:
                written = False

        if self.frame_callback:
            try:
                self.frame_callback(png_bytes, metadata, opacity)
            except Exception:
                pass

        return written

    def _perform_fade(self, metadata: Dict[str, str], start_opacity: float, end_opacity: float, target_state: TransitionState):
        with self._lock:
            self._state = target_state

        step_count = max(1, int(self.fade_duration * self.steps_per_sec))
        step_interval = self.fade_duration / step_count

        for i in range(step_count + 1):
            if not self._running:
                break
            progress = i / step_count
            opacity = start_opacity + (end_opacity - start_opacity) * progress
            self._emit_frame(metadata, opacity)
            if i < step_count:
                time.sleep(step_interval)

    def _run_loop(self):
        while self._running:
            # Check for pending update
            with self._lock:
                pending = self._pending_metadata
                self._pending_metadata = None

            if pending is None:
                self._wake_event.wait(timeout=0.1)
                self._wake_event.clear()
                continue

            # Check if pending is identical to what's already visible
            if self.current_metadata == pending:
                continue

            # 1. Fade out old metadata if present
            if self.current_metadata is not None:
                self._perform_fade(self.current_metadata, start_opacity=1.0, end_opacity=0.0, target_state=TransitionState.FADING_OUT)

            if not self._running:
                break

            # 2. Swap metadata while invisible
            with self._lock:
                self._state = TransitionState.SWAP
                # While we were fading out, did another newer valid update arrive?
                if self._pending_metadata is not None:
                    # Latest valid metadata wins at swap point
                    pending = self._pending_metadata
                    self._pending_metadata = None
                    self.total_coalesced += 1

                self.current_metadata = pending
                self.last_known_good_metadata = pending

            # Emit exact 0.0 opacity frame with swapped metadata to confirm invisible swap
            self._emit_frame(self.current_metadata, 0.0)

            # 3. Fade in new metadata
            self._perform_fade(self.current_metadata, start_opacity=0.0, end_opacity=1.0, target_state=TransitionState.FADING_IN)

            if not self._running:
                break

            with self._lock:
                self._state = TransitionState.VISIBLE
                self.total_transitions_completed += 1

            # Emit final full opacity frame (1.0)
            self._emit_frame(self.current_metadata, 1.0)
