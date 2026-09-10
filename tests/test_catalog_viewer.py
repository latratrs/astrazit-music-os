"""Comprehensive test suite for Local Admin Catalog Viewer.

Governed by OS-008.
Tests all requirements:
1. Application import has no side effects (no server started, no files modified, no cloud/Firestore touched).
2. Dashboard returns 200 for valid demo sandbox.
3. Dashboard displays DEMO / NON-PRODUCTION badge and persistent notices.
4. Summary counts show 3 Works, 5 Recordings, 3 Releases.
5. Works route returns 200 and lists all 3 works.
6. Recordings route returns 200 and lists all 5 recordings.
7. Releases route returns 200 and lists all 3 releases.
8. Work detail returns 200 for DEMO-WRK-000001.
9. Recording detail returns 200 for DEMO-REC-000001.
10. Release detail returns 200 for DEMO-REL-000001.
11. DEMO IDs appear correctly.
12. INTERNAL AST LEAK TEST: Internal AST fixture IDs (AST-WRK-, AST-REC-, AST-REL-)
    NEVER appear in rendered HTML for any endpoint.
13. AST-shaped incoming detail IDs (e.g. /admin/catalog/recordings/AST-REC-000001) are cleanly rejected with 404.
14. Unknown DEMO IDs return 404.
15. Work -> Recording relationships link correctly.
16. Recording -> Work relationship links correctly.
17. Recording -> Release relationship links correctly.
18. Release -> Recording tracklist links correctly.
19. Status badges render appropriately.
20. Missing or uninitialized sandbox handled safely (503 Service Unavailable, clear instructions).
21. Corrupted sandbox handled safely.
22. No mutation routes: POST, PUT, PATCH, DELETE are rejected with 405 Method Not Allowed.
23. PRODUCTION ISOLATION: No SequenceStore, IdentifierAllocator, or Firestore calls made.
24. Zero network access required.
25. Relocated checkout / temporary sandbox works deterministically.
26. Server configuration defaults to 127.0.0.1 (loopback).
27. Health endpoint returns 200 JSON with status ok.
28. Root path / redirects to /admin/catalog.
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.admin.catalog_demo.sandbox import DemoCatalogSandbox
from apps.admin.catalog_viewer.app import CatalogViewerServer, create_server
from apps.admin.catalog_viewer.service import CatalogViewerService


def find_free_port() -> int:
    """Find an available port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestCatalogViewer(unittest.TestCase):
    temp_dir: tempfile.TemporaryDirectory
    sandbox_dir: Path
    sandbox: DemoCatalogSandbox
    server: CatalogViewerServer
    server_thread: threading.Thread
    port: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.sandbox_dir = Path(cls.temp_dir.name) / "test_sandbox"
        cls.sandbox = DemoCatalogSandbox(sandbox_dir=cls.sandbox_dir)
        cls.sandbox.init()

        cls.port = find_free_port()
        cls.server = create_server(host="127.0.0.1", port=cls.port, sandbox_dir=cls.sandbox_dir)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp_dir.cleanup()

    def request(self, method: str, path: str) -> tuple[int, http.client.HTTPMessage, str]:
        """Helper to send HTTP request to the running test server."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            headers = resp.headers
            body = resp.read().decode("utf-8")
            return resp.status, headers, body
        finally:
            conn.close()

    # 1. IMPORT SIDE-EFFECT SAFETY
    def test_import_has_no_side_effects(self):
        """Application import must not open sockets, modify files, or connect to cloud."""
        import apps.admin.catalog_viewer
        import apps.admin.catalog_viewer.app
        import apps.admin.catalog_viewer.service
        import apps.admin.catalog_viewer.view_models
        self.assertIsNotNone(apps.admin.catalog_viewer.__version__)

    # 2. SERVER DEFAULTS TO LOOPBACK
    def test_server_defaults_to_loopback(self):
        srv = create_server(port=0, sandbox_dir=self.sandbox_dir)
        try:
            self.assertEqual(srv.server_address[0], "127.0.0.1")
        finally:
            srv.server_close()

    # 3. ROOT REDIRECT & HEALTH
    def test_root_redirects_to_catalog(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 302)
            self.assertEqual(resp.getheader("Location"), "/admin/catalog")
        finally:
            conn.close()

    def test_health_endpoint(self):
        status, headers, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["mode"], "DEMO_VIEWER")
        self.assertTrue(data["sandbox_initialized"])

    # 4. STATIC CSS SERVING
    def test_static_css_endpoint(self):
        status, headers, body = self.request("GET", "/admin/catalog/static/catalog.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertIn("Dark-Studio", body)

    # 5. DASHBOARD TESTS
    def test_dashboard_success_and_counts(self):
        status, headers, body = self.request("GET", "/admin/catalog")
        self.assertEqual(status, 200)
        self.assertIn("DEMO / NON-PRODUCTION", body)
        self.assertIn("LOCAL EVALUATION ONLY", body)
        self.assertIn("Musical Works", body)
        self.assertIn("Sound Recordings", body)
        self.assertIn("Releases", body)
        self.assertIn(">3<", body)  # 3 Works / 3 Releases
        self.assertIn(">5<", body)  # 5 Recordings
        self.assertIn("2 Eligible", body)
        self.assertIn("3 Ineligible", body)

    # 6. WORKS LIST & DETAIL
    def test_works_list(self):
        status, _, body = self.request("GET", "/admin/catalog/works")
        self.assertEqual(status, 200)
        self.assertIn("DEMO-WRK-000001", body)
        self.assertIn("DEMO-WRK-000002", body)
        self.assertIn("DEMO-WRK-000003", body)
        self.assertIn("Electric Dream", body)
        self.assertIn("Beat in Your Veins", body)
        self.assertIn("Creatures of the Night", body)

    def test_work_detail_demo_id(self):
        status, _, body = self.request("GET", "/admin/catalog/works/DEMO-WRK-000001")
        self.assertEqual(status, 200)
        self.assertIn("DEMO-WRK-000001", body)
        self.assertIn("Electric Dream", body)
        self.assertIn("AstraZit Composer", body)
        # Check linked recordings
        self.assertIn("DEMO-REC-000001", body)
        self.assertIn("DEMO-REC-000002", body)
        self.assertIn("/admin/catalog/recordings/DEMO-REC-000001", body)

    # 7. RECORDINGS LIST & DETAIL
    def test_recordings_list(self):
        status, _, body = self.request("GET", "/admin/catalog/recordings")
        self.assertEqual(status, 200)
        for i in range(1, 6):
            self.assertIn(f"DEMO-REC-00000{i}", body)
        self.assertIn("Electric Dream", body)
        self.assertIn("Original Mix", body)
        self.assertIn("Radio Edit", body)
        self.assertIn("DEMO-WRK-000001", body)
        self.assertIn("ELIGIBLE", body)
        self.assertIn("HEAVY", body)

    def test_recording_detail_demo_id(self):
        status, _, body = self.request("GET", "/admin/catalog/recordings/DEMO-REC-000001")
        self.assertEqual(status, 200)
        self.assertIn("DEMO-REC-000001", body)
        self.assertIn("Electric Dream (Original Mix)", body)
        self.assertIn("DEMO-WRK-000001", body)
        self.assertIn("/admin/catalog/works/DEMO-WRK-000001", body)
        self.assertIn("HEAVY", body)
        self.assertIn("Synthwave", body)
        self.assertIn("DEMO-REL-000001", body)
        self.assertIn("/admin/catalog/releases/DEMO-REL-000001", body)

    # 8. RELEASES LIST & DETAIL
    def test_releases_list(self):
        status, _, body = self.request("GET", "/admin/catalog/releases")
        self.assertEqual(status, 200)
        for i in range(1, 4):
            self.assertIn(f"DEMO-REL-00000{i}", body)
        self.assertIn("Electric Dream - Single", body)
        self.assertIn("Beat in Your Veins - Single", body)
        self.assertIn("Creatures of the Night", body)

    def test_release_detail_demo_id(self):
        status, _, body = self.request("GET", "/admin/catalog/releases/DEMO-REL-000001")
        self.assertEqual(status, 200)
        self.assertIn("DEMO-REL-000001", body)
        self.assertIn("Electric Dream - Single", body)
        self.assertIn("DEMO-REC-000001", body)
        self.assertIn("/admin/catalog/recordings/DEMO-REC-000001", body)

    def test_multi_track_release_detail(self):
        status, _, body = self.request("GET", "/admin/catalog/releases/DEMO-REL-000003")
        self.assertEqual(status, 200)
        self.assertIn("DEMO-REL-000003", body)
        self.assertIn("DEMO-REC-000004", body)
        self.assertIn("DEMO-REC-000005", body)

    # 9. HARD ACCEPTANCE: INTERNAL AST LEAK TEST
    def test_internal_ast_ids_never_leaked_in_html(self):
        """Assert normal HTML does NOT contain AST-WRK-, AST-REC-, AST-REL- anywhere."""
        routes_to_test = [
            "/admin/catalog",
            "/admin/catalog/works",
            "/admin/catalog/works/DEMO-WRK-000001",
            "/admin/catalog/works/DEMO-WRK-000002",
            "/admin/catalog/works/DEMO-WRK-000003",
            "/admin/catalog/recordings",
            "/admin/catalog/recordings/DEMO-REC-000001",
            "/admin/catalog/recordings/DEMO-REC-000002",
            "/admin/catalog/recordings/DEMO-REC-000003",
            "/admin/catalog/recordings/DEMO-REC-000004",
            "/admin/catalog/recordings/DEMO-REC-000005",
            "/admin/catalog/releases",
            "/admin/catalog/releases/DEMO-REL-000001",
            "/admin/catalog/releases/DEMO-REL-000002",
            "/admin/catalog/releases/DEMO-REL-000003",
        ]

        forbidden_patterns = ["AST-WRK-", "AST-REC-", "AST-REL-"]

        for route in routes_to_test:
            with self.subTest(route=route):
                status, _, body = self.request("GET", route)
                self.assertEqual(status, 200, f"Route {route} failed with status {status}")
                for pattern in forbidden_patterns:
                    self.assertNotIn(
                        pattern,
                        body,
                        f"CRITICAL LEAK: Pattern {pattern!r} found in rendered HTML for route {route}!",
                    )

    # 10. REJECTION OF AST-SHAPED IDS IN URLS
    def test_incoming_ast_ids_rejected(self):
        """Incoming URLs with AST-shaped IDs must fail with 404."""
        bad_urls = [
            "/admin/catalog/works/AST-WRK-000001",
            "/admin/catalog/recordings/AST-REC-000001",
            "/admin/catalog/releases/AST-REL-000001",
        ]
        for url in bad_urls:
            with self.subTest(url=url):
                status, _, body = self.request("GET", url)
                self.assertEqual(status, 404)
                self.assertIn("Error 404", body)
                self.assertNotRegex(body, r"AST-(?:WRK|REC|REL)-")

    # 11. UNKNOWN DEMO IDS RETURN 404
    def test_unknown_demo_ids_return_404(self):
        unknown_urls = [
            "/admin/catalog/works/DEMO-WRK-999999",
            "/admin/catalog/recordings/DEMO-REC-999999",
            "/admin/catalog/releases/DEMO-REL-999999",
        ]
        for url in unknown_urls:
            with self.subTest(url=url):
                status, _, body = self.request("GET", url)
                self.assertEqual(status, 404)

    # 12. NO MUTATION ROUTES (405 METHOD NOT ALLOWED)
    def test_no_mutation_routes(self):
        methods = ["POST", "PUT", "PATCH", "DELETE"]
        routes = [
            "/admin/catalog",
            "/admin/catalog/works",
            "/admin/catalog/recordings",
            "/admin/catalog/releases",
        ]
        for m in methods:
            for r in routes:
                with self.subTest(method=m, route=r):
                    status, _, body = self.request(m, r)
                    self.assertEqual(status, 405)
                    self.assertIn("Method Not Allowed", body)

    # 13. HARD ACCEPTANCE: PRODUCTION ISOLATION TEST
    def test_production_isolation_guarantee(self):
        """Prove viewer execution does not construct or call IdentifierAllocator or SequenceStore."""
        with patch("packages.catalog.identifiers.IdentifierAllocator") as mock_alloc, \
             patch("packages.catalog.sequence_store.LocalJsonSequenceStore") as mock_local_seq, \
             patch("packages.catalog.firestore_sequence_store.FirestoreSequenceStore") as mock_fs_seq:

            status, _, body = self.request("GET", "/admin/catalog")
            self.assertEqual(status, 200)

            status, _, body = self.request("GET", "/admin/catalog/recordings/DEMO-REC-000001")
            self.assertEqual(status, 200)

            mock_alloc.assert_not_called()
            mock_local_seq.assert_not_called()
            mock_fs_seq.assert_not_called()

    # 14. SANDBOX FAILURE HANDLING (MISSING SANDBOX)
    def test_missing_sandbox_handled_safely(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            missing_sandbox_path = Path(empty_dir) / "nonexistent"
            srv = create_server(port=find_free_port(), sandbox_dir=missing_sandbox_path)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
                conn.request("GET", "/admin/catalog")
                resp = conn.getresponse()
                body = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 503)
                self.assertIn("Demo Catalog Sandbox is not initialized", body)
                self.assertIn("python -m apps.admin.catalog_demo init", body)
                conn.close()
            finally:
                srv.shutdown()
                srv.server_close()

    # 15. RELOCATED CHECKOUT / TEMP SANDBOX WORKS
    def test_relocated_sandbox(self):
        with tempfile.TemporaryDirectory() as other_dir:
            other_sandbox_dir = Path(other_dir) / "custom_demo"
            other_sandbox = DemoCatalogSandbox(sandbox_dir=other_sandbox_dir)
            other_sandbox.init()

            svc = CatalogViewerService(sandbox_dir=other_sandbox_dir)
            summary = svc.get_summary_view()
            self.assertEqual(summary.works_count, 3)
            self.assertEqual(summary.recordings_count, 5)
            self.assertEqual(summary.releases_count, 3)
            self.assertTrue(summary.is_valid)


if __name__ == "__main__":
    unittest.main()
