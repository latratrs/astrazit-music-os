"""CLI interface for AstraZit Music OS Local Demo Catalog.

Governed by OS-007.
Provides:
  init [--force]
  summary
  list <works|recordings|releases>
  show <DEMO-ID>
  validate
  reset [--yes]

Standard library only, deterministic formatting, clean non-zero exits on errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from apps.admin.catalog_demo.sandbox import (
    DemoCatalogSandbox,
    DemoMappingError,
    DemoSandboxError,
    SandboxSafetyError,
    SandboxUninitializedError,
)
from packages.catalog.identifiers import EntityType
from packages.catalog.repository import CatalogError


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format simple aligned plain text table."""
    if not rows:
        return "No records found.\n"
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(val)))
            else:
                col_widths.append(len(str(val)))

    lines = []
    header_str = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_str = "  ".join("-" * col_widths[i] for i in range(len(headers)))
    lines.append(header_str)
    lines.append(sep_str)
    for row in rows:
        lines.append("  ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(row))))
    return "\n".join(lines) + "\n"


def cmd_init(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    try:
        counts = sandbox.init(force=args.force)
        print(f"SUCCESS: Initialized demo catalog sandbox at {sandbox.sandbox_dir}")
        print(f"  Works:      {counts['works']}")
        print(f"  Recordings: {counts['recordings']}")
        print(f"  Releases:   {counts['releases']}")
        print("\nAll sample fixtures validated through CatalogRepository and persisted safely.")
        print("Run 'summary' or 'list works' to inspect the demo data.")
        return 0
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Failed to initialize sandbox: {exc}", file=sys.stderr)
        return 1


def cmd_summary(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    try:
        data = sandbox.summary()
        print("=" * 60)
        print("ASTRAZIT MUSIC OS -- LOCAL DEMO CATALOG SUMMARY")
        print("=" * 60)
        print(f"Location:  {data['sandbox_path']}")
        print(f"Mode:      NON-PRODUCTION DEMO SANDBOX\n")

        counts = data["counts"]
        print(f"Entities Total:")
        print(f"  Works:               {counts['works']}")
        print(f"  Recordings:          {counts['recordings']}")
        print(f"  Releases:            {counts['releases']}\n")

        print("Rights Approval Status:")
        print("  Composition (Works):")
        for st, c in sorted(data["composition_rights"].items()):
            print(f"    {st.ljust(25)}: {c}")
        print("  Master (Recordings):")
        for st, c in sorted(data["master_rights"].items()):
            print(f"    {st.ljust(25)}: {c}\n")

        radio = data["radio"]
        print("Radio Broadcast Eligibility:")
        print(f"  Eligible:            {radio['eligible']}")
        print(f"  Ineligible:          {radio['ineligible']}\n")

        print("Release Lifecycle:")
        for st, c in sorted(data["release_lifecycle"].items()):
            print(f"  {st.ljust(27)}: {c}")
        print("=" * 60)
        return 0
    except SandboxUninitializedError:
        print("ERROR: Sandbox is not initialized. Run 'init' first.", file=sys.stderr)
        return 1
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Failed to load summary: {exc}", file=sys.stderr)
        return 1


def cmd_list(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    target = args.entity_type.lower()
    try:
        if target in ("work", "works"):
            items = sandbox.list_entities(EntityType.WORK)
            headers = ["DEMO ID", "TITLE", "ORIGIN", "STATUS", "RIGHTS"]
            rows = [
                [item["demo_id"], item["title"], item["origin"], item["lifecycle"], item["rights"]]
                for item in items
            ]
            print(format_table(headers, rows))
        elif target in ("recording", "recordings"):
            items = sandbox.list_entities(EntityType.RECORDING)
            headers = ["DEMO ID", "TITLE / VERSION", "WORK ID", "STATUS", "RIGHTS", "RADIO", "TIER"]
            rows = [
                [
                    item["demo_id"], item["title"],
                    item["work_id"], item["lifecycle"], item["rights"],
                    item["radio"], item["rotation"]
                ]
                for item in items
            ]
            print(format_table(headers, rows))
        elif target in ("release", "releases"):
            items = sandbox.list_entities(EntityType.RELEASE)
            headers = ["DEMO ID", "TITLE", "TYPE", "STATUS", "TRACKS", "TRACKLIST"]
            rows = [
                [
                    item["demo_id"], item["title"],
                    item["type"], item["lifecycle"], str(item["tracks_count"]),
                    ", ".join(item["tracks"])
                ]
                for item in items
            ]
            print(format_table(headers, rows))
        else:
            print(f"ERROR: Unknown entity type '{args.entity_type}'. Must be works, recordings, or releases.", file=sys.stderr)
            return 2
        return 0
    except SandboxUninitializedError:
        print("ERROR: Sandbox is not initialized. Run 'init' first.", file=sys.stderr)
        return 1
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Failed to list {target}: {exc}", file=sys.stderr)
        return 1


def cmd_show(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    identifier = args.identifier.strip()
    try:
        etype, doc = sandbox.get_entity(identifier)
        demo_id = sandbox.to_demo_id(identifier)
        if identifier.upper().startswith("AST-"):
            raise DemoMappingError("CLI accepts DEMO identifiers only")
        internal_id = sandbox.to_internal_id(identifier)

        print("=" * 60)
        print(f"ASTRAZIT MUSIC OS -- {etype.value} DETAILS")
        print("=" * 60)
        print(f"Demo ID:       {demo_id}")
        print(f"Type:          {etype.value}")
        print(f"Origin:        {doc.get('catalog_origin')}")
        print(f"Lifecycle:     {doc.get('lifecycle_status')}")

        if etype == EntityType.WORK:
            print(f"Title:         {doc.get('canonical_title')}")
            rights = doc.get("composition_rights", {})
            print("\n[Composition Rights]")
            print(f"  Approval:    {rights.get('approval_status')}")
            if rights.get("approved_by"):
                print(f"  Approved By: {rights.get('approved_by')} @ {rights.get('approved_at')}")
            print(f"  Copyright:   {rights.get('copyright_notice_composition', 'None')}")
            print("  Writers:")
            for w in rights.get("writers", []):
                print(f"    - {w.get('name')} ({w.get('role')}): {w.get('percentage')}%")
            print("  Publishers:")
            for p in rights.get("publishers", []):
                print(f"    - {p.get('name')}: {p.get('percentage')}%")

        elif etype == EntityType.RECORDING:
            print(f"Title:         {doc.get('recording_title')} -- {doc.get('version')}")
            print(f"Artist:        {doc.get('artist')}")
            work_internal = doc.get("astrazit_work_id")
            work_demo = sandbox.to_demo_id(work_internal)
            print(f"Linked Work:   {work_demo}")
            music = doc.get("music", {})
            print(f"Music Specs:   {music.get('genre')} | {music.get('bpm')} BPM | {music.get('duration_seconds')}s | {music.get('key')} {music.get('scale')}")

            m_rights = doc.get("master_rights", {})
            print("\n[Master Rights]")
            print(f"  Approval:    {m_rights.get('approval_status')}")
            if m_rights.get("approved_by"):
                print(f"  Approved By: {m_rights.get('approved_by')} @ {m_rights.get('approved_at')}")
            print(f"  ISRC:        {m_rights.get('isrc', 'None (Demo)')}")
            print("  Owners:")
            for o in m_rights.get("owners", []):
                print(f"    - {o.get('name')}: {o.get('percentage')}%")

            radio = doc.get("radio", {})
            print("\n[Radio Metadata]")
            print(f"  Eligible:    {radio.get('radio_eligible', False)}")
            print(f"  Status:      {radio.get('eligibility_status')}")
            print(f"  Tier:        {radio.get('rotation_tier', 'None')}")
            if radio.get("daypart_candidates"):
                print(f"  Dayparts:    {', '.join(radio.get('daypart_candidates'))}")
            if radio.get("programming_notes"):
                print(f"  Notes:       {radio.get('programming_notes')}")

        elif etype == EntityType.RELEASE:
            print(f"Title:         {doc.get('title')}")
            print(f"Artist:        {doc.get('artist')}")
            print(f"Release Type:  {doc.get('release_type')}")
            print(f"Release Date:  {doc.get('release_date', 'Unscheduled')}")
            print(f"UPC:           {doc.get('upc', 'None (Demo)')}")
            print("\n[Tracklist]")
            for track in doc.get("tracklist", []):
                rec_internal = track.get("astrazit_recording_id")
                rec_demo = sandbox.to_demo_id(rec_internal)
                t_num = track.get("track_number")
                d_num = track.get("disc_number", 1)
                print(f"  Track {t_num} (Disc {d_num}): {rec_demo}")

        print("=" * 60)
        return 0
    except SandboxUninitializedError:
        print("ERROR: Sandbox is not initialized. Run 'init' first.", file=sys.stderr)
        return 1
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Failed to show entity '{identifier}': {exc}", file=sys.stderr)
        return 1


def cmd_validate(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    try:
        res = sandbox.validate()
        if res["valid"]:
            print("PASS: Demo catalog sandbox validation passed successfully.")
            print("  - All Work, Recording, and Release records pass Draft 2020-12 schemas")
            print("  - Cross-entity referential integrity verified")
            print("  - Rights approval rules and release-readiness invariants verified")
            print("  - Public DEMO ID translation mapping verified")
            return 0
        else:
            print("FAIL: Demo catalog sandbox validation failed:", file=sys.stderr)
            for issue in res["issues"]:
                print(f"  - {issue}", file=sys.stderr)
            return 1
    except SandboxUninitializedError:
        print("ERROR: Sandbox is not initialized. Run 'init' first.", file=sys.stderr)
        return 1
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Validation aborted due to system error: {exc}", file=sys.stderr)
        return 1


def cmd_reset(sandbox: DemoCatalogSandbox, args: argparse.Namespace) -> int:
    if not args.yes:
        try:
            confirm = input(f"Are you sure you want to reset and delete demo sandbox at {sandbox.sandbox_dir}? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            print("ERROR: Reset confirmation was not provided.", file=sys.stderr)
            return 1
        if confirm.strip().lower() not in ("y", "yes"):
            print("Reset cancelled.")
            return 0
    try:
        sandbox.reset(confirmed=True, recreate=args.recreate)
        if args.recreate:
            print(f"SUCCESS: Reset and re-initialized demo sandbox at {sandbox.sandbox_dir}")
        else:
            print(f"SUCCESS: Cleaned up demo sandbox at {sandbox.sandbox_dir}")
        return 0
    except (CatalogError, DemoSandboxError) as exc:
        print(f"ERROR: Failed to reset sandbox: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apps.admin.catalog_demo",
        description="AstraZit Music OS -- Local Demo Catalog Sandbox CLI",
    )
    parser.add_argument(
        "--sandbox-dir",
        type=str,
        default=None,
        help="Custom sandbox root directory (default: .local/demo-catalog/)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize sample catalog fixtures in local sandbox")
    p_init.add_argument("--force", action="store_true", help="Force overwrite if sandbox already exists")

    # summary
    subparsers.add_parser("summary", help="Show summary statistics of demo catalog sandbox")

    # list
    p_list = subparsers.add_parser("list", help="List catalog entities")
    p_list.add_argument("entity_type", choices=["works", "recordings", "releases", "work", "recording", "release"], help="Type of entity to list")

    # show
    p_show = subparsers.add_parser("show", help="Display detailed view of a demo entity")
    p_show.add_argument("identifier", type=str, help="Public demo ID (e.g. DEMO-WRK-000001)")

    # validate
    subparsers.add_parser("validate", help="Validate catalog records and referential integrity")

    # reset
    p_reset = subparsers.add_parser("reset", help="Wipe and reset local demo sandbox")
    p_reset.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    p_reset.add_argument("--recreate", action="store_true", help="Re-initialize fresh fixtures after wipe")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    sandbox = DemoCatalogSandbox(sandbox_dir=args.sandbox_dir)

    handlers = {
        "init": cmd_init,
        "summary": cmd_summary,
        "list": cmd_list,
        "show": cmd_show,
        "validate": cmd_validate,
        "reset": cmd_reset,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(sandbox, args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
