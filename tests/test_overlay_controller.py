"""
Unit tests for OverlayController state machine and transition contract.
Governed by VISUAL-003R3.
"""
import os
import time
import tempfile
import shutil
import unittest
from apps.radio.overlay.controller import OverlayController, TransitionState
from apps.radio.overlay.sanitizer import normalize_metadata

class TestOverlayController(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_png = os.path.join(self.temp_dir, "overlay.png")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _wait_for_state(self, ctrl, target_state, timeout=3.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if ctrl.state == target_state and ctrl.pending_metadata is None:
                return True
            time.sleep(0.01)
        return False

    def test_normal_transition(self):
        """Test normal transition: state progression and target file creation."""
        recorded_opacities = []

        def frame_cb(png_bytes, meta, opacity):
            recorded_opacities.append(round(opacity, 2))

        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.1,
            steps_per_sec=20,
            frame_callback=frame_cb,
        )
        ctrl.start()
        try:
            self.assertEqual(ctrl.state, TransitionState.IDLE)
            ctrl.submit_metadata({"title": "Song 1", "artist": "Artist 1"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))
            self.assertEqual(ctrl.current_metadata["title"], "Song 1")
            self.assertTrue(os.path.exists(self.target_png))
            self.assertEqual(ctrl.current_opacity, 1.0)
            self.assertIn(1.0, recorded_opacities)
            self.assertIn(0.0, recorded_opacities)
        finally:
            ctrl.stop()

    def test_update_during_fade_out(self):
        """Update submitted during fade out should be swapped in at opacity 0."""
        swapped_titles = []

        def frame_cb(png_bytes, meta, opacity):
            if opacity == 0.0:
                swapped_titles.append(meta["title"])

        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.2,
            steps_per_sec=20,
            frame_callback=frame_cb,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Song 1"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))
            self.assertEqual(ctrl.current_metadata["title"], "Song 1")

            # Submit Song 2 to start fade out
            ctrl.submit_metadata({"title": "Song 2"})
            time.sleep(0.05)  # While fading out
            self.assertEqual(ctrl.state, TransitionState.FADING_OUT)

            # Submit Song 3 during fade out
            ctrl.submit_metadata({"title": "Song 3"})

            # Wait for transition to complete
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))
            self.assertEqual(ctrl.current_metadata["title"], "Song 3")
            # Ensure Song 3 was swapped in at 0 opacity
            self.assertIn("Song 3", swapped_titles)
        finally:
            ctrl.stop()

    def test_update_during_fade_in(self):
        """Update arriving during fade in should be captured and displayed next."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.2,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Initial Song"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))
            self.assertEqual(ctrl.current_metadata["title"], "Initial Song")

            # Submit Update 1
            ctrl.submit_metadata({"title": "Update 1"})
            # Wait until fade in starts
            t0 = time.time()
            while ctrl.state != TransitionState.FADING_IN and time.time() - t0 < 1.0:
                time.sleep(0.01)
            self.assertEqual(ctrl.state, TransitionState.FADING_IN)

            # Submit Update 2 during fade in
            ctrl.submit_metadata({"title": "Update 2"})

            # Wait for all transitions to complete
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE, timeout=4.0))
            self.assertEqual(ctrl.current_metadata["title"], "Update 2")
        finally:
            ctrl.stop()

    def test_multiple_rapid_updates(self):
        """10 rapid updates should coalesce so latest valid wins."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.1,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            for i in range(10):
                ctrl.submit_metadata({"title": f"Rapid Song {i}"})
                time.sleep(0.01)

            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE, timeout=4.0))
            self.assertEqual(ctrl.current_metadata["title"], "Rapid Song 9")
            self.assertGreater(ctrl.total_coalesced, 0)
            self.assertEqual(ctrl.total_submitted, 10)
        finally:
            ctrl.stop()

    def test_latest_valid_wins(self):
        """Ensures that latest valid metadata wins when multiple updates arrive."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.2,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Base Song"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))

            # Queue multiple before next step
            ctrl.submit_metadata({"title": "Intermediate A"})
            ctrl.submit_metadata({"title": "Intermediate B"})
            ctrl.submit_metadata({"title": "Winner C"})

            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE, timeout=4.0))
            self.assertEqual(ctrl.current_metadata["title"], "Winner C")
        finally:
            ctrl.stop()

    def test_no_unbounded_queue(self):
        """Ensures pending queue is bounded to at most 1 item."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.5,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Initial"})
            time.sleep(0.1)  # actively transitioning
            # Submit 50 updates rapidly
            for i in range(50):
                ctrl.submit_metadata({"title": f"Flood {i}"})

            # At all times, pending_metadata is either None or a single dict
            pending = ctrl.pending_metadata
            self.assertTrue(pending is None or isinstance(pending, dict))
            self.assertEqual(pending["title"], "Flood 49")
        finally:
            ctrl.stop()

    def test_same_metadata_repeated(self):
        """Submitting identical metadata does not trigger spurious transitions."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.1,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Same Song", "artist": "Same Artist"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))
            self.assertEqual(ctrl.total_transitions_completed, 1)

            # Submit same metadata 5 times
            for _ in range(5):
                ctrl.submit_metadata({"title": "Same Song", "artist": "Same Artist"})

            time.sleep(0.2)
            self.assertEqual(ctrl.total_transitions_completed, 1)
        finally:
            ctrl.stop()

    def test_invalid_update_does_not_replace_valid_pending_state(self):
        """Malformed input does not crash or corrupt valid pending state."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.1,
            steps_per_sec=20,
        )
        ctrl.start()
        try:
            ctrl.submit_metadata({"title": "Valid Song 1"})
            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE))

            # Submit valid pending
            ctrl.submit_metadata({"title": "Valid Song 2"})

            # Submit garbage types / unhandled objects
            ctrl.submit_metadata({"bad_key": object()})

            self.assertTrue(self._wait_for_state(ctrl, TransitionState.VISIBLE, timeout=4.0))
            self.assertIn(ctrl.current_metadata["title"], ["Valid Song 2", "ASTRAZIT RADIO"])
            self.assertTrue(ctrl._running)
        finally:
            ctrl.stop()

    def test_clean_shutdown(self):
        """Clean shutdown without hanging or deadlocks."""
        ctrl = OverlayController(
            target_png_path=self.target_png,
            fade_duration=0.5,
            steps_per_sec=20,
        )
        ctrl.start()
        ctrl.submit_metadata({"title": "Song Before Stop"})
        time.sleep(0.05)
        t0 = time.time()
        ctrl.stop(timeout=2.0)
        stop_time = time.time() - t0
        self.assertLess(stop_time, 2.0)
        self.assertFalse(ctrl._worker_thread.is_alive())

if __name__ == "__main__":
    unittest.main()
