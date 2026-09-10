"""Command line entrypoint for AstraZit Music OS Local Admin Catalog Viewer.

Governed by OS-008.
Starts a local-only, read-only HTTP server bound to loopback (127.0.0.1) by default.

Usage:
    python -m apps.admin.catalog_viewer [--port PORT] [--host HOST] [--sandbox-dir DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apps.admin.catalog_viewer.app import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AstraZit Music OS — Local Admin Catalog Viewer (Read-Only Demo)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind (loopback only by default)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on",
    )
    parser.add_argument(
        "--sandbox-dir",
        type=Path,
        default=None,
        help="Optional path to custom demo catalog sandbox directory",
    )

    args = parser.parse_args(argv)

    try:
        server = create_server(
            host=args.host,
            port=args.port,
            sandbox_dir=args.sandbox_dir,
        )
    except Exception as exc:
        print(f"Error initializing catalog viewer server: {exc}", file=sys.stderr)
        return 1

    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/admin/catalog"

    print("=" * 60)
    print("ASTRAZIT MUSIC OS — LOCAL ADMIN CATALOG VIEWER")
    print("=" * 60)
    print(f"URL:     {url}")
    print(f"Bind:    {actual_host}:{actual_port}")
    print("Mode:    DEMO / NON-PRODUCTION (READ-ONLY)")
    print("Notice:  No mutations permitted. Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping catalog viewer...")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
