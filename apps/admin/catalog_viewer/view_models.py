"""Read-only view models for the Local Admin Catalog Viewer.

Governed by OS-008.
These dataclasses translate raw repository documents into safe presentation models,
ensuring internal fixture AST identifiers are completely absent and replaced with
user-facing DEMO identifiers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class CatalogSummaryView:
    sandbox_path_display: str
    is_valid: bool
    validation_issues: list[str]
    works_count: int
    recordings_count: int
    releases_count: int
    composition_rights_counts: dict[str, int]
    master_rights_counts: dict[str, int]
    release_lifecycle_counts: dict[str, int]
    radio_eligible_count: int
    radio_ineligible_count: int


@dataclass(frozen=True)
class LinkedItem:
    demo_id: str
    title: str
    url: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None


@dataclass(frozen=True)
class WorkListItem:
    demo_id: str
    canonical_title: str
    catalog_origin: str
    lifecycle_status: str
    composition_rights_status: str
    writers_count: int
    linked_recordings_count: int
    detail_url: str


@dataclass(frozen=True)
class WriterPublisherSplit:
    name: str
    role: str
    percentage: float


@dataclass(frozen=True)
class ProvenanceView:
    source: str
    source_system: str
    generated_at: str
    approval_status: str
    approver: Optional[str] = None
    approved_at: Optional[str] = None
    version: int = 1
    canonical_status: str = "PROVISIONAL"
    notes: Optional[str] = None


@dataclass(frozen=True)
class WorkDetailView:
    demo_id: str
    canonical_title: str
    catalog_origin: str
    lifecycle_status: str
    composition_rights_status: str
    copyright_notice: Optional[str]
    writers: list[WriterPublisherSplit]
    publishers: list[WriterPublisherSplit]
    linked_recordings: list[LinkedItem]
    provenance: Optional[ProvenanceView] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class RecordingListItem:
    demo_id: str
    recording_title: str
    version: str
    display_title: str
    work_demo_id: str
    work_title: str
    work_url: str
    lifecycle_status: str
    master_rights_status: str
    radio_eligible: bool
    rotation_tier: str
    duration_formatted: str
    bpm_key_display: str
    detail_url: str


@dataclass(frozen=True)
class RecordingDetailView:
    demo_id: str
    recording_title: str
    version: str
    display_title: str
    artist: str
    work_demo_id: str
    work_title: str
    work_url: str
    lifecycle_status: str
    catalog_origin: str
    master_rights_status: str
    copyright_notice: Optional[str]
    owners: list[WriterPublisherSplit]
    duration_formatted: str
    bpm: Optional[float]
    key_scale: str
    genre: str
    subgenres: list[str]
    moods: list[str]
    energy: Optional[float]
    radio_eligible: bool
    radio_eligibility_status: str
    rotation_tier: str
    radio_programming_notes: Optional[str]
    daypart_candidates: list[str]
    content_id_status: Optional[str]
    soundexchange_status: Optional[str]
    linked_releases: list[LinkedItem]
    provenance: Optional[ProvenanceView] = None


@dataclass(frozen=True)
class ReleaseTrackItem:
    track_number: int
    disc_number: int
    recording_demo_id: str
    recording_title: str
    recording_url: str
    duration_formatted: str


@dataclass(frozen=True)
class ReleaseListItem:
    demo_id: str
    title: str
    artist: str
    release_type: str
    catalog_origin: str
    lifecycle_status: str
    release_date: Optional[str]
    tracks_count: int
    detail_url: str


@dataclass(frozen=True)
class DistributionItem:
    provider: str
    status: str
    external_release_id: Optional[str] = None


@dataclass(frozen=True)
class ArtworkMetadataItem:
    asset_id: str
    asset_type: str
    mime_type: str


@dataclass(frozen=True)
class ReleaseDetailView:
    demo_id: str
    title: str
    artist: str
    release_type: str
    catalog_origin: str
    lifecycle_status: str
    release_date: Optional[str]
    tracklist: list[ReleaseTrackItem]
    distribution: list[DistributionItem]
    artwork_metadata: list[ArtworkMetadataItem]
    provenance: Optional[ProvenanceView] = None
