"""HTTP server application and request routing for AstraZit Music OS catalog viewer.

Governed by OS-008.
Provides a local, read-only HTTP server strictly bound to loopback (127.0.0.1) by default.
Features:
- No mutation endpoints (POST/PUT/PATCH/DELETE fail with 405 Method Not Allowed).
- Routes for Dashboard, Works list/detail, Recordings list/detail, Releases list/detail.
- Root redirect to /admin/catalog.
- Static CSS asset serving.
- Clean error pages on missing/uninitialized sandbox or 404s.
"""
from __future__ import annotations

import http.server
import json
import logging
import re
import urllib.parse
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Union

from apps.admin.catalog_demo.sandbox import (
    DemoMappingError,
    DemoSandboxError,
    SandboxSafetyError,
    SandboxUninitializedError,
)
from apps.admin.catalog_viewer import renderer
from apps.admin.catalog_viewer.service import (
    DEMO_REC_ID_PATTERN,
    DEMO_REL_ID_PATTERN,
    DEMO_WORK_ID_PATTERN,
    CatalogViewerService,
)
from packages.catalog.repository import CatalogError, CatalogNotFoundError

logger = logging.getLogger("catalog_viewer")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class CatalogViewerRequestHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the read-only catalog viewer."""

    server_version = "AstraZitCatalogViewer/1.0"

    @property
    def service(self) -> CatalogViewerService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        """Use Python logger instead of stderr dumping."""
        logger.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def do_HEAD(self) -> None:
        self.do_GET(head_only=True)

    def do_GET(self, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        try:
            # 1. Health check
            if path == "/health":
                self._send_json(
                    {
                        "status": "ok",
                        "mode": "DEMO_VIEWER",
                        "sandbox_initialized": self.service.is_sandbox_initialized(),
                    },
                    head_only=head_only,
                )
                return

            # 2. Root redirect
            if path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/admin/catalog")
                self.end_headers()
                return

            # 3. Static CSS
            if path == "/admin/catalog/static/catalog.css":
                css_file = STATIC_DIR / "catalog.css"
                if not css_file.exists():
                    self._send_error(404, "Static file not found", head_only=head_only)
                    return
                content = css_file.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                if not head_only:
                    self.wfile.write(content)
                return

            # 4. Check sandbox readiness before rendering catalog views
            if not self.service.is_sandbox_initialized():
                body = renderer.render_error_page(
                    status_code=503,
                    message="Demo Catalog Sandbox is not initialized or marker is missing.",
                    resolution_hint="Run: python -m apps.admin.catalog_demo init",
                )
                self._send_html(body, status=HTTPStatus.SERVICE_UNAVAILABLE, head_only=head_only)
                return

            # 5. Dashboard
            if path == "/admin/catalog":
                summary = self.service.get_summary_view()
                html_body = renderer.render_dashboard(summary)
                self._send_html(html_body, head_only=head_only)
                return

            # 6. Works list
            if path == "/admin/catalog/works":
                works = self.service.list_works()
                html_body = renderer.render_works_list(works)
                self._send_html(html_body, head_only=head_only)
                return

            # 7. Work detail
            m_work = re.match(r"^/admin/catalog/works/([^/]+)$", path)
            if m_work:
                demo_id = m_work.group(1)
                # Reject AST IDs explicitly or malformed IDs with 404
                if not DEMO_WORK_ID_PATTERN.fullmatch(demo_id):
                    self._send_error(
                        404,
                        "Work not found. URLs must use DEMO-WRK-XXXXXX identifiers.",
                        head_only=head_only,
                    )
                    return
                work_detail = self.service.get_work_detail(demo_id)
                html_body = renderer.render_work_detail(work_detail)
                self._send_html(html_body, head_only=head_only)
                return

            # 8. Recordings list
            if path == "/admin/catalog/recordings":
                recordings = self.service.list_recordings()
                html_body = renderer.render_recordings_list(recordings)
                self._send_html(html_body, head_only=head_only)
                return

            # 9. Recording detail
            m_rec = re.match(r"^/admin/catalog/recordings/([^/]+)$", path)
            if m_rec:
                demo_id = m_rec.group(1)
                if not DEMO_REC_ID_PATTERN.fullmatch(demo_id):
                    self._send_error(
                        404,
                        "Recording not found. URLs must use DEMO-REC-XXXXXX identifiers.",
                        head_only=head_only,
                    )
                    return
                rec_detail = self.service.get_recording_detail(demo_id)
                html_body = renderer.render_recording_detail(rec_detail)
                self._send_html(html_body, head_only=head_only)
                return

            # 10. Releases list
            if path == "/admin/catalog/releases":
                releases = self.service.list_releases()
                html_body = renderer.render_releases_list(releases)
                self._send_html(html_body, head_only=head_only)
                return

            # 11. Release detail
            m_rel = re.match(r"^/admin/catalog/releases/([^/]+)$", path)
            if m_rel:
                demo_id = m_rel.group(1)
                if not DEMO_REL_ID_PATTERN.fullmatch(demo_id):
                    self._send_error(
                        404,
                        "Release not found. URLs must use DEMO-REL-XXXXXX identifiers.",
                        head_only=head_only,
                    )
                    return
                rel_detail = self.service.get_release_detail(demo_id)
                html_body = renderer.render_release_detail(rel_detail)
                self._send_html(html_body, head_only=head_only)
                return

            # Route not matched
            self._send_error(404, "Page not found.", head_only=head_only)

        except (CatalogNotFoundError, DemoMappingError) as exc:
            self._send_error(404, str(exc), head_only=head_only)
        except (SandboxUninitializedError, SandboxSafetyError, CatalogError) as exc:
            logger.exception("Catalog or sandbox error processing %s: %s", path, exc)
            self._send_error(
                500,
                "Catalog repository error. Please validate the local demo sandbox.",
                resolution_hint="Run: python -m apps.admin.catalog_demo validate",
                head_only=head_only,
            )
        except Exception as exc:
            logger.exception("Unexpected error processing %s: %s", path, exc)
            self._send_error(500, "Internal server error occurred.", head_only=head_only)

    def do_POST(self) -> None:
        self._send_method_not_allowed()

    def do_PUT(self) -> None:
        self._send_method_not_allowed()

    def do_PATCH(self) -> None:
        self._send_method_not_allowed()

    def do_DELETE(self) -> None:
        self._send_method_not_allowed()

    def _send_method_not_allowed(self) -> None:
        body = renderer.render_error_page(
            status_code=405,
            message="Method Not Allowed: Catalog viewer is strictly read-only.",
            resolution_hint="Catalog mutations cannot be performed via the browser viewer.",
        )
        self._send_html(body, status=HTTPStatus.METHOD_NOT_ALLOWED)

    def _send_html(self, content_str: str, status: int = 200, head_only: bool = False) -> None:
        content_bytes = content_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content_bytes)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if not head_only:
            self.wfile.write(content_bytes)

    def _send_json(self, data: dict, status: int = 200, head_only: bool = False) -> None:
        content_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content_bytes)))
        self.end_headers()
        if not head_only:
            self.wfile.write(content_bytes)

    def _send_error(self, status: int, message: str, resolution_hint: Optional[str] = None, head_only: bool = False) -> None:
        body = renderer.render_error_page(status, message, resolution_hint=resolution_hint)
        self._send_html(body, status=status, head_only=head_only)


class CatalogViewerServer(http.server.ThreadingHTTPServer):
    """Threaded HTTP server holding the CatalogViewerService instance."""

    def __init__(
        self,
        server_address: tuple[str, int],
        sandbox_dir: Optional[Union[Path, str]] = None,
    ) -> None:
        self.service = CatalogViewerService(sandbox_dir=sandbox_dir)
        super().__init__(server_address, CatalogViewerRequestHandler)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    sandbox_dir: Optional[Union[Path, str]] = None,
) -> CatalogViewerServer:
    """Create and return a configured CatalogViewerServer without starting it."""
    return CatalogViewerServer((host, port), sandbox_dir=sandbox_dir)
