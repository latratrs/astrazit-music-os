"""Catalog viewer service layer for AstraZit Music OS.

Governed by OS-008.
Encapsulates all interaction with DemoCatalogSandbox and LocalJsonCatalogRepository.
Translates repository documents into safe view models and guarantees that internal
fixture AST identifiers are never leaked to presentation models or URLs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Union

from apps.admin.catalog_demo.sandbox import (
    DemoCatalogSandbox,
    DemoMappingError,
    DemoSandboxError,
    SandboxSafetyError,
    SandboxUninitializedError,
)
from apps.admin.catalog_viewer.view_models import (
    ArtworkMetadataItem,
    CatalogSummaryView,
    DistributionItem,
    LinkedItem,
    ProvenanceView,
    RecordingDetailView,
    RecordingListItem,
    ReleaseDetailView,
    ReleaseListItem,
    ReleaseTrackItem,
    WorkDetailView,
    WorkListItem,
    WriterPublisherSplit,
)
from packages.catalog.identifiers import EntityType
from packages.catalog.repository import CatalogNotFoundError

DEMO_WORK_ID_PATTERN = re.compile(r"^DEMO-WRK-[0-9]{6}$")
DEMO_REC_ID_PATTERN = re.compile(r"^DEMO-REC-[0-9]{6}$")
DEMO_REL_ID_PATTERN = re.compile(r"^DEMO-REL-[0-9]{6}$")


def format_duration(seconds: Optional[Union[float, int]]) -> str:
    if seconds is None:
        return "--:--"
    total_sec = int(round(seconds))
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}:{secs:02d}"


def _make_provenance_view(prov: Optional[dict[str, Any]]) -> Optional[ProvenanceView]:
    if not prov or not isinstance(prov, dict):
        return None
    return ProvenanceView(
        source=str(prov.get("source", "UNKNOWN")),
        source_system=str(prov.get("source_system", "UNKNOWN")),
        generated_at=str(prov.get("generated_at", "")),
        approval_status=str(prov.get("approval_status", "UNKNOWN")),
        approver=prov.get("approver"),
        approved_at=prov.get("approved_at"),
        version=int(prov.get("version", 1)),
        canonical_status=str(prov.get("canonical_status", "PROVISIONAL")),
        notes=prov.get("notes"),
    )


class CatalogViewerService:
    """Read-only service adapting the demo sandbox to safe view models."""

    def __init__(self, sandbox_dir: Optional[Union[Path, str]] = None) -> None:
        self.sandbox = DemoCatalogSandbox(sandbox_dir=sandbox_dir)

    def is_sandbox_initialized(self) -> bool:
        return self.sandbox.is_initialized()

    def get_summary_view(self) -> CatalogSummaryView:
        """Construct the catalog summary view model."""
        summary = self.sandbox.summary()
        val_result = self.sandbox.validate()

        # Hide full absolute path for presentation safety; display relative or sanitized
        raw_path = Path(summary["sandbox_path"])
        display_path = f".../{raw_path.parent.name}/{raw_path.name}" if raw_path.parent else str(raw_path)

        return CatalogSummaryView(
            sandbox_path_display=display_path,
            is_valid=val_result.get("valid", False),
            validation_issues=val_result.get("issues", []),
            works_count=summary["counts"]["works"],
            recordings_count=summary["counts"]["recordings"],
            releases_count=summary["counts"]["releases"],
            composition_rights_counts=summary.get("composition_rights", {}),
            master_rights_counts=summary.get("master_rights", {}),
            release_lifecycle_counts=summary.get("release_lifecycle", {}),
            radio_eligible_count=summary.get("radio", {}).get("eligible", 0),
            radio_ineligible_count=summary.get("radio", {}).get("ineligible", 0),
        )

    def list_works(self) -> list[WorkListItem]:
        """Return list of works formatted for display."""
        repo = self.sandbox.repository
        work_internal_ids = repo.list_ids(EntityType.WORK)
        rec_internal_ids = repo.list_ids(EntityType.RECORDING)

        # Precompute work -> recording counts
        work_rec_counts: dict[str, int] = {}
        for rid in rec_internal_ids:
            rec_doc = repo.get(EntityType.RECORDING, rid)
            wid = rec_doc.get("astrazit_work_id", "")
            work_rec_counts[wid] = work_rec_counts.get(wid, 0) + 1

        items: list[WorkListItem] = []
        for wid in work_internal_ids:
            doc = repo.get(EntityType.WORK, wid)
            demo_id = self.sandbox.to_demo_id(wid)
            comp_rights = doc.get("composition_rights", {})
            writers = comp_rights.get("writers", [])

            items.append(
                WorkListItem(
                    demo_id=demo_id,
                    canonical_title=doc.get("canonical_title", "Untitled Work"),
                    catalog_origin=doc.get("catalog_origin", "UNKNOWN"),
                    lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
                    composition_rights_status=comp_rights.get("approval_status", "UNKNOWN"),
                    writers_count=len(writers),
                    linked_recordings_count=work_rec_counts.get(wid, 0),
                    detail_url=f"/admin/catalog/works/{demo_id}",
                )
            )
        return items

    def get_work_detail(self, demo_id: str) -> WorkDetailView:
        """Retrieve work detail by DEMO ID only. Rejects internal AST IDs."""
        if not DEMO_WORK_ID_PATTERN.fullmatch(demo_id):
            raise CatalogNotFoundError(f"Invalid or rejected Work demo identifier: {demo_id}")

        internal_id = self.sandbox.to_internal_id(demo_id)
        repo = self.sandbox.repository
        doc = repo.get(EntityType.WORK, internal_id)

        # Find linked recordings
        linked_recs: list[LinkedItem] = []
        for rid in repo.list_ids(EntityType.RECORDING):
            rec_doc = repo.get(EntityType.RECORDING, rid)
            if rec_doc.get("astrazit_work_id") == internal_id:
                rec_demo_id = self.sandbox.to_demo_id(rid)
                title = f"{rec_doc.get('recording_title', '')} ({rec_doc.get('version', '')})"
                badge = rec_doc.get("lifecycle_status")
                linked_recs.append(
                    LinkedItem(
                        demo_id=rec_demo_id,
                        title=title,
                        url=f"/admin/catalog/recordings/{rec_demo_id}",
                        subtitle=f"Master Rights: {rec_doc.get('master_rights', {}).get('approval_status', '')}",
                        badge=badge,
                    )
                )

        comp_rights = doc.get("composition_rights", {})
        writers = [
            WriterPublisherSplit(
                name=w.get("name", ""),
                role=w.get("role", ""),
                percentage=float(w.get("percentage", 0.0)),
            )
            for w in comp_rights.get("writers", [])
        ]
        publishers = [
            WriterPublisherSplit(
                name=p.get("name", ""),
                role=p.get("role", ""),
                percentage=float(p.get("percentage", 0.0)),
            )
            for p in comp_rights.get("publishers", [])
        ]

        return WorkDetailView(
            demo_id=demo_id,
            canonical_title=doc.get("canonical_title", "Untitled Work"),
            catalog_origin=doc.get("catalog_origin", "UNKNOWN"),
            lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
            composition_rights_status=comp_rights.get("approval_status", "UNKNOWN"),
            copyright_notice=comp_rights.get("copyright_notice_composition"),
            writers=writers,
            publishers=publishers,
            linked_recordings=linked_recs,
            provenance=_make_provenance_view(doc.get("provenance")),
            notes=comp_rights.get("notes"),
        )

    def list_recordings(self) -> list[RecordingListItem]:
        """Return list of recordings formatted for display."""
        repo = self.sandbox.repository
        rec_internal_ids = repo.list_ids(EntityType.RECORDING)

        # Cache works for fast title lookups
        work_titles: dict[str, str] = {}
        for wid in repo.list_ids(EntityType.WORK):
            wdoc = repo.get(EntityType.WORK, wid)
            work_titles[wid] = wdoc.get("canonical_title", "")

        items: list[RecordingListItem] = []
        for rid in rec_internal_ids:
            doc = repo.get(EntityType.RECORDING, rid)
            demo_id = self.sandbox.to_demo_id(rid)
            wid = doc.get("astrazit_work_id", "")
            work_demo_id = self.sandbox.to_demo_id(wid)
            work_title = work_titles.get(wid, "Unknown Work")

            rec_title = doc.get("recording_title", "")
            version = doc.get("version", "")
            display_title = f"{rec_title} ({version})" if version else rec_title

            music = doc.get("music", {})
            duration = music.get("duration_seconds")
            bpm = music.get("bpm")
            key = music.get("key", "")
            scale = music.get("scale", "")
            bpm_key_parts = []
            if bpm:
                bpm_key_parts.append(f"{bpm:g} BPM")
            if key:
                bpm_key_parts.append(f"{key} {scale}".strip())
            bpm_key_display = " / ".join(bpm_key_parts) if bpm_key_parts else "-"

            radio = doc.get("radio", {})
            radio_eligible = radio.get("radio_eligible", False)
            rotation = radio.get("rotation_tier", "-")

            master_rights = doc.get("master_rights", {})

            items.append(
                RecordingListItem(
                    demo_id=demo_id,
                    recording_title=rec_title,
                    version=version,
                    display_title=display_title,
                    work_demo_id=work_demo_id,
                    work_title=work_title,
                    work_url=f"/admin/catalog/works/{work_demo_id}",
                    lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
                    master_rights_status=master_rights.get("approval_status", "UNKNOWN"),
                    radio_eligible=radio_eligible,
                    rotation_tier=rotation,
                    duration_formatted=format_duration(duration),
                    bpm_key_display=bpm_key_display,
                    detail_url=f"/admin/catalog/recordings/{demo_id}",
                )
            )
        return items

    def get_recording_detail(self, demo_id: str) -> RecordingDetailView:
        """Retrieve recording detail by DEMO ID only. Rejects internal AST IDs."""
        if not DEMO_REC_ID_PATTERN.fullmatch(demo_id):
            raise CatalogNotFoundError(f"Invalid or rejected Recording demo identifier: {demo_id}")

        internal_id = self.sandbox.to_internal_id(demo_id)
        repo = self.sandbox.repository
        doc = repo.get(EntityType.RECORDING, internal_id)

        # Linked Work
        wid = doc.get("astrazit_work_id", "")
        work_demo_id = self.sandbox.to_demo_id(wid)
        work_doc = repo.get(EntityType.WORK, wid) if repo.exists(EntityType.WORK, wid) else {}
        work_title = work_doc.get("canonical_title", "Unknown Work")

        # Linked Releases
        linked_releases: list[LinkedItem] = []
        for rlid in repo.list_ids(EntityType.RELEASE):
            rel_doc = repo.get(EntityType.RELEASE, rlid)
            tracklist = rel_doc.get("tracklist", [])
            for track in tracklist:
                if track.get("astrazit_recording_id") == internal_id:
                    rel_demo_id = self.sandbox.to_demo_id(rlid)
                    linked_releases.append(
                        LinkedItem(
                            demo_id=rel_demo_id,
                            title=rel_doc.get("title", ""),
                            url=f"/admin/catalog/releases/{rel_demo_id}",
                            subtitle=f"Track #{track.get('track_number', 1)} | Type: {rel_doc.get('release_type', '')}",
                            badge=rel_doc.get("lifecycle_status"),
                        )
                    )
                    break

        music = doc.get("music", {})
        key = music.get("key", "")
        scale = music.get("scale", "")
        key_scale = f"{key} {scale}".strip() if (key or scale) else "-"

        master_rights = doc.get("master_rights", {})
        owners = [
            WriterPublisherSplit(
                name=o.get("name", ""),
                role="OWNER",
                percentage=float(o.get("percentage", 0.0)),
            )
            for o in master_rights.get("owners", [])
        ]

        content_id = master_rights.get("content_id", {}).get("status")
        soundexchange = master_rights.get("soundexchange_status", {}).get("status")

        radio = doc.get("radio", {})
        rec_title = doc.get("recording_title", "")
        version = doc.get("version", "")
        display_title = f"{rec_title} ({version})" if version else rec_title

        return RecordingDetailView(
            demo_id=demo_id,
            recording_title=rec_title,
            version=version,
            display_title=display_title,
            artist=doc.get("artist", "AstraZit"),
            work_demo_id=work_demo_id,
            work_title=work_title,
            work_url=f"/admin/catalog/works/{work_demo_id}",
            lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
            catalog_origin=doc.get("catalog_origin", "UNKNOWN"),
            master_rights_status=master_rights.get("approval_status", "UNKNOWN"),
            copyright_notice=master_rights.get("copyright_notice_sound_recording"),
            owners=owners,
            duration_formatted=format_duration(music.get("duration_seconds")),
            bpm=music.get("bpm"),
            key_scale=key_scale,
            genre=music.get("genre", "-"),
            subgenres=music.get("subgenres", []),
            moods=music.get("moods", []),
            energy=music.get("energy"),
            radio_eligible=radio.get("radio_eligible", False),
            radio_eligibility_status=radio.get("eligibility_status", "UNSPECIFIED"),
            rotation_tier=radio.get("rotation_tier", "-"),
            radio_programming_notes=radio.get("programming_notes"),
            daypart_candidates=radio.get("daypart_candidates", []),
            content_id_status=content_id,
            soundexchange_status=soundexchange,
            linked_releases=linked_releases,
            provenance=_make_provenance_view(doc.get("provenance")),
        )

    def list_releases(self) -> list[ReleaseListItem]:
        """Return list of releases formatted for display."""
        repo = self.sandbox.repository
        rel_internal_ids = repo.list_ids(EntityType.RELEASE)

        items: list[ReleaseListItem] = []
        for rlid in rel_internal_ids:
            doc = repo.get(EntityType.RELEASE, rlid)
            demo_id = self.sandbox.to_demo_id(rlid)
            tracklist = doc.get("tracklist", [])

            items.append(
                ReleaseListItem(
                    demo_id=demo_id,
                    title=doc.get("title", ""),
                    artist=doc.get("artist", "AstraZit"),
                    release_type=doc.get("release_type", "SINGLE"),
                    catalog_origin=doc.get("catalog_origin", "UNKNOWN"),
                    lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
                    release_date=doc.get("release_date"),
                    tracks_count=len(tracklist),
                    detail_url=f"/admin/catalog/releases/{demo_id}",
                )
            )
        return items

    def get_release_detail(self, demo_id: str) -> ReleaseDetailView:
        """Retrieve release detail by DEMO ID only. Rejects internal AST IDs."""
        if not DEMO_REL_ID_PATTERN.fullmatch(demo_id):
            raise CatalogNotFoundError(f"Invalid or rejected Release demo identifier: {demo_id}")

        internal_id = self.sandbox.to_internal_id(demo_id)
        repo = self.sandbox.repository
        doc = repo.get(EntityType.RELEASE, internal_id)

        # Tracklist with translated DEMO-REC links
        tracklist_items: list[ReleaseTrackItem] = []
        for t in doc.get("tracklist", []):
            rec_id = t.get("astrazit_recording_id", "")
            rec_demo_id = self.sandbox.to_demo_id(rec_id)
            rec_doc = repo.get(EntityType.RECORDING, rec_id) if repo.exists(EntityType.RECORDING, rec_id) else {}
            rtitle = rec_doc.get("recording_title", "Unknown Track")
            rver = rec_doc.get("version", "")
            full_title = f"{rtitle} ({rver})" if rver else rtitle
            dur = rec_doc.get("music", {}).get("duration_seconds")

            tracklist_items.append(
                ReleaseTrackItem(
                    track_number=int(t.get("track_number", 1)),
                    disc_number=int(t.get("disc_number", 1)),
                    recording_demo_id=rec_demo_id,
                    recording_title=full_title,
                    recording_url=f"/admin/catalog/recordings/{rec_demo_id}",
                    duration_formatted=format_duration(dur),
                )
            )

        # Distribution info (demo-safe)
        dist_items = [
            DistributionItem(
                provider=d.get("provider", ""),
                status=d.get("status", ""),
                external_release_id=d.get("external_release_id"),
            )
            for d in doc.get("distribution", [])
        ]

        # Artwork metadata (demo-safe, no local filesystem path exposed)
        artwork_items = [
            ArtworkMetadataItem(
                asset_id=a.get("asset_id", ""),
                asset_type=a.get("asset_type", ""),
                mime_type=a.get("mime_type", ""),
            )
            for a in doc.get("artwork", [])
        ]

        return ReleaseDetailView(
            demo_id=demo_id,
            title=doc.get("title", ""),
            artist=doc.get("artist", "AstraZit"),
            release_type=doc.get("release_type", "SINGLE"),
            catalog_origin=doc.get("catalog_origin", "UNKNOWN"),
            lifecycle_status=doc.get("lifecycle_status", "DRAFT"),
            release_date=doc.get("release_date"),
            tracklist=tracklist_items,
            distribution=dist_items,
            artwork_metadata=artwork_items,
            provenance=_make_provenance_view(doc.get("provenance")),
        )
