"""Deterministic sample catalog fixtures for AstraZit Music OS local demo.

Governed by OS-007.
All data here is purely fictional/demo metadata for local sandbox evaluation.
NO real copyright ownership, PRO registrations, ISRC/UPC codes, or production
identities are claimed or allocated.
"""
from __future__ import annotations

import copy
from typing import Any

# Public demo identifier mapping to isolated internal fixture AST IDs
DEMO_TO_INTERNAL_ID = {
    "DEMO-WRK-000001": "AST-WRK-000001",
    "DEMO-WRK-000002": "AST-WRK-000002",
    "DEMO-WRK-000003": "AST-WRK-000003",
    "DEMO-REC-000001": "AST-REC-000001",
    "DEMO-REC-000002": "AST-REC-000002",
    "DEMO-REC-000003": "AST-REC-000003",
    "DEMO-REC-000004": "AST-REC-000004",
    "DEMO-REC-000005": "AST-REC-000005",
    "DEMO-REL-000001": "AST-REL-000001",
    "DEMO-REL-000002": "AST-REL-000002",
    "DEMO-REL-000003": "AST-REL-000003",
}

INTERNAL_TO_DEMO_ID = {v: k for k, v in DEMO_TO_INTERNAL_ID.items()}

# ---------------------------------------------------------------------------
# WORKS (3)
# ---------------------------------------------------------------------------
WORK_FIXTURES: list[dict[str, Any]] = [
    {
        "schema_version": "1.0.0",
        "astrazit_work_id": "AST-WRK-000001",
        "canonical_title": "Electric Dream",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "ACTIVE",
        "composition_rights": {
            "approval_status": "APPROVED",
            "approved_by": "demo-rights-admin",
            "approved_at": "2026-09-01T12:00:00Z",
            "copyright_notice_composition": "(C) 2026 AstraZit Demo Publishing",
            "writers": [
                {
                    "name": "AstraZit Composer",
                    "role": "AUTHOR_COMPOSER",
                    "percentage": 100.0,
                }
            ],
            "publishers": [
                {
                    "name": "AstraZit Demo Music",
                    "role": "PUBLISHER",
                    "percentage": 100.0,
                }
            ],
        },
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-01T10:00:00Z",
            "approval_status": "APPROVED",
            "approver": "demo-rights-admin",
            "approved_at": "2026-09-01T12:00:00Z",
            "version": 1,
            "canonical_status": "MASTER_METADATA",
            "notes": "DEMO FIXTURE: Non-production sample catalog work for Electric Dream.",
        },
    },
    {
        "schema_version": "1.0.0",
        "astrazit_work_id": "AST-WRK-000002",
        "canonical_title": "Beat in Your Veins",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "ACTIVE",
        "composition_rights": {
            "approval_status": "PENDING_HUMAN_APPROVAL",
            "copyright_notice_composition": "(C) 2026 AstraZit Demo Publishing",
            "writers": [
                {
                    "name": "AstraZit Writer A",
                    "role": "COMPOSER",
                    "percentage": 60.0,
                },
                {
                    "name": "AstraZit Writer B",
                    "role": "AUTHOR",
                    "percentage": 40.0,
                },
            ],
            "publishers": [
                {
                    "name": "AstraZit Demo Music",
                    "role": "PUBLISHER",
                    "percentage": 100.0,
                }
            ],
            "notes": "Pending split contract signature verification.",
        },
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-02T10:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Non-production sample catalog work for Beat in Your Veins with pending rights.",
        },
    },
    {
        "schema_version": "1.0.0",
        "astrazit_work_id": "AST-WRK-000003",
        "canonical_title": "Creatures of the Night",
        "catalog_origin": "HISTORICAL_IMPORT",
        "lifecycle_status": "ACTIVE",
        "composition_rights": {
            "approval_status": "PENDING_HUMAN_APPROVAL",
            "copyright_notice_composition": "(C) 2024 AstraZit Legacy",
            "writers": [
                {
                    "name": "Legacy AstraZit Writer",
                    "role": "AUTHOR_COMPOSER",
                    "percentage": 100.0,
                }
            ],
            "publishers": [
                {
                    "name": "Legacy AstraZit Catalog",
                    "role": "PUBLISHER",
                    "percentage": 100.0,
                }
            ],
            "notes": "Historical composition imported from pre-Music OS distributor report.",
        },
        "provenance": {
            "source": "IMPORTED",
            "source_system": "legacy_demo_import",
            "generated_at": "2024-06-01T00:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Historical import demo work for Creatures of the Night.",
        },
        "historical_import": {
            "first_released_at": "2024-06-01T00:00:00Z",
            "imported_at": "2026-09-01T00:00:00Z",
            "source_reference": "https://demo.astrazit.local/legacy-import/creatures",
            "rights_review_required": True,
        },
    },
]

# ---------------------------------------------------------------------------
# RECORDINGS (5)
# ---------------------------------------------------------------------------
RECORDING_FIXTURES: list[dict[str, Any]] = [
    # 1. Electric Dream - Original Mix (Work 1, Approved, Radio Eligible Heavy)
    {
        "schema_version": "1.0.0",
        "astrazit_recording_id": "AST-REC-000001",
        "astrazit_work_id": "AST-WRK-000001",
        "recording_title": "Electric Dream",
        "version": "Original Mix",
        "artist": "AstraZit",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "RELEASE_READY",
        "music": {
            "duration_seconds": 218.0,
            "bpm": 122.0,
            "key": "F#",
            "scale": "MINOR",
            "genre": "Synthwave",
            "subgenres": ["Outrun", "Chillsynth"],
            "moods": ["Driving", "Euphoric", "Nocturnal"],
            "energy": 0.78,
            "language": "en",
        },
        "assets": [
            {
                "asset_id": "demo-asset-rec-000001-master",
                "asset_type": "MASTER_WAV",
                "uri": "file:///demo-storage/AST-REC-000001/Electric_Dream_Original.wav",
                "mime_type": "audio/wav",
                "checksum_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size_bytes": 62000000,
                "format_details": {
                    "sample_rate_hz": 48000,
                    "bit_depth": 24,
                    "channels": 2,
                },
                "created_at": "2026-09-01T11:00:00Z",
            }
        ],
        "master_rights": {
            "copyright_notice_sound_recording": "(P) 2026 AstraZit Demo Masters",
            "soundexchange_status": {
                "status": "UNREGISTERED",
            },
            "content_id": {
                "status": "EXCLUDED",
            },
            "owners": [
                {
                    "name": "AstraZit Demo Music LLC",
                    "percentage": 100.0,
                }
            ],
            "approval_status": "APPROVED",
            "approved_by": "demo-master-reviewer",
            "approved_at": "2026-09-01T12:00:00Z",
        },
        "radio": {
            "radio_eligible": True,
            "eligibility_status": "APPROVED",
            "rotation_tier": "HEAVY",
            "daypart_candidates": ["PRIME_EVENING", "LATE_NIGHT"],
            "mood_tags": ["HighEnergy", "NeonDrive", "Peak"],
            "energy_rating": 0.82,
            "intro_duration_seconds": 15.0,
            "outro_duration_seconds": 12.0,
            "programming_notes": "Flagship synthwave cut; excellent for prime evening drive.",
        },
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-01T11:00:00Z",
            "approval_status": "APPROVED",
            "approver": "demo-master-reviewer",
            "approved_at": "2026-09-01T12:00:00Z",
            "version": 1,
            "canonical_status": "MASTER_METADATA",
            "notes": "DEMO FIXTURE: Non-production sample recording for Electric Dream (Original Mix).",
        },
    },
    # 2. Electric Dream - Radio Edit (Work 1, Approved, Radio Eligible Medium)
    {
        "schema_version": "1.0.0",
        "astrazit_recording_id": "AST-REC-000002",
        "astrazit_work_id": "AST-WRK-000001",
        "recording_title": "Electric Dream",
        "version": "Radio Edit",
        "artist": "AstraZit",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "RELEASE_READY",
        "music": {
            "duration_seconds": 185.0,
            "bpm": 122.0,
            "key": "F#",
            "scale": "MINOR",
            "genre": "Synthwave",
            "subgenres": ["Outrun", "Synthpop"],
            "moods": ["Driving", "Catchy", "Upbeat"],
            "energy": 0.84,
            "language": "en",
        },
        "assets": [
            {
                "asset_id": "demo-asset-rec-000002-master",
                "asset_type": "STREAM_DERIVATIVE",
                "uri": "file:///demo-storage/AST-REC-000002/Electric_Dream_RadioEdit.mp3",
                "mime_type": "audio/mpeg",
            }
        ],
        "master_rights": {
            "copyright_notice_sound_recording": "(P) 2026 AstraZit Demo Masters",
            "owners": [
                {
                    "name": "AstraZit Demo Music LLC",
                    "percentage": 100.0,
                }
            ],
            "approval_status": "APPROVED",
            "approved_by": "demo-master-reviewer",
            "approved_at": "2026-09-01T12:00:00Z",
        },
        "radio": {
            "radio_eligible": True,
            "eligibility_status": "APPROVED",
            "rotation_tier": "MEDIUM",
            "daypart_candidates": ["MORNING", "DRIVE_TIME", "MIDDAY"],
            "mood_tags": ["Bright", "Compact", "Commute"],
            "energy_rating": 0.85,
            "intro_duration_seconds": 6.0,
            "outro_duration_seconds": 8.0,
            "programming_notes": "Tight intro for radio host voiceover ducking.",
        },
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-01T11:30:00Z",
            "approval_status": "APPROVED",
            "approver": "demo-master-reviewer",
            "approved_at": "2026-09-01T12:00:00Z",
            "version": 1,
            "canonical_status": "MASTER_METADATA",
            "notes": "DEMO FIXTURE: Non-production radio cut for Electric Dream.",
        },
    },
    # 3. Beat in Your Veins - Original Mix (Work 2, Draft Rights, Ineligible / Pending Curation)
    {
        "schema_version": "1.0.0",
        "astrazit_recording_id": "AST-REC-000003",
        "astrazit_work_id": "AST-WRK-000002",
        "recording_title": "Beat in Your Veins",
        "version": "Original Mix",
        "artist": "AstraZit",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "DRAFT",
        "music": {
            "duration_seconds": 245.0,
            "bpm": 128.0,
            "key": "D",
            "scale": "MINOR",
            "genre": "Electro",
            "subgenres": ["Cyberpunk", "Darksynth"],
            "moods": ["Intense", "Pounding", "Aggressive"],
            "energy": 0.92,
            "language": "zxx",
        },
        "master_rights": {
            "copyright_notice_sound_recording": "(P) 2026 AstraZit Demo Masters",
            "owners": [
                {
                    "name": "AstraZit Demo Music LLC",
                    "percentage": 100.0,
                }
            ],
            "approval_status": "DRAFT",
        },
        "radio": {
            "radio_eligible": False,
            "eligibility_status": "PENDING_CURATION",
            "rotation_tier": "LIGHT",
            "programming_notes": "Awaiting final master loudness audit and composition split approval.",
        },
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-02T11:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Draft recording for Beat in Your Veins.",
        },
    },
    # 4. Creatures of the Night - Original Mix (Work 3, Historical Released, Pending Rights, Ineligible / Restricted)
    {
        "schema_version": "1.0.0",
        "astrazit_recording_id": "AST-REC-000004",
        "astrazit_work_id": "AST-WRK-000003",
        "recording_title": "Creatures of the Night",
        "version": "Original Mix",
        "artist": "AstraZit",
        "catalog_origin": "HISTORICAL_IMPORT",
        "lifecycle_status": "RELEASED",
        "music": {
            "duration_seconds": 204.0,
            "bpm": 116.0,
            "key": "A",
            "scale": "MINOR",
            "genre": "Darkwave",
            "subgenres": ["Gothic Synth", "EBM"],
            "moods": ["Shadowy", "Hypnotic", "Moody"],
            "energy": 0.70,
            "language": "en",
        },
        "master_rights": {
            "copyright_notice_sound_recording": "(P) 2024 AstraZit Legacy",
            "owners": [
                {
                    "name": "Legacy AstraZit Catalog",
                    "percentage": 100.0,
                }
            ],
            "approval_status": "PENDING_HUMAN_APPROVAL",
        },
        "radio": {
            "radio_eligible": False,
            "eligibility_status": "RESTRICTED",
            "rotation_tier": "SPECIALTY",
            "programming_notes": "Restricted from daytime playout pending complete master contract audit.",
        },
        "provenance": {
            "source": "IMPORTED",
            "source_system": "legacy_demo_import",
            "generated_at": "2024-06-01T00:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Historical recording import for Creatures of the Night.",
        },
        "historical_import": {
            "first_released_at": "2024-06-01T00:00:00Z",
            "imported_at": "2026-09-01T00:00:00Z",
            "source_reference": "https://demo.astrazit.local/legacy-import/creatures-rec1",
            "rights_review_required": True,
        },
    },
    # 5. Creatures of the Night - Extended Mix (Work 3, Historical Released, Pending Rights, Ineligible / Pending Curation)
    {
        "schema_version": "1.0.0",
        "astrazit_recording_id": "AST-REC-000005",
        "astrazit_work_id": "AST-WRK-000003",
        "recording_title": "Creatures of the Night",
        "version": "Extended Mix",
        "artist": "AstraZit",
        "catalog_origin": "HISTORICAL_IMPORT",
        "lifecycle_status": "RELEASED",
        "music": {
            "duration_seconds": 340.0,
            "bpm": 116.0,
            "key": "A",
            "scale": "MINOR",
            "genre": "Darkwave",
            "subgenres": ["Club Mix", "Extended Synth"],
            "moods": ["Extended", "Hypnotic", "Nocturnal"],
            "energy": 0.75,
            "language": "en",
        },
        "master_rights": {
            "copyright_notice_sound_recording": "(P) 2024 AstraZit Legacy",
            "owners": [
                {
                    "name": "Legacy AstraZit Catalog",
                    "percentage": 100.0,
                }
            ],
            "approval_status": "PENDING_HUMAN_APPROVAL",
        },
        "radio": {
            "radio_eligible": False,
            "eligibility_status": "PENDING_CURATION",
            "rotation_tier": "LATE_NIGHT",
            "programming_notes": "Extended club cut; pending curation for midnight specialty block.",
        },
        "provenance": {
            "source": "IMPORTED",
            "source_system": "legacy_demo_import",
            "generated_at": "2024-06-01T00:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Historical extended mix import for Creatures of the Night.",
        },
        "historical_import": {
            "first_released_at": "2024-06-01T00:00:00Z",
            "imported_at": "2026-09-01T00:00:00Z",
            "source_reference": "https://demo.astrazit.local/legacy-import/creatures-rec2",
            "rights_review_required": True,
        },
    },
]

# ---------------------------------------------------------------------------
# RELEASES (3)
# ---------------------------------------------------------------------------
RELEASE_FIXTURES: list[dict[str, Any]] = [
    # 1. Electric Dream - Single (Native, Release Ready, contains Recording 1)
    {
        "schema_version": "1.0.0",
        "astrazit_release_id": "AST-REL-000001",
        "title": "Electric Dream - Single",
        "artist": "AstraZit",
        "release_type": "SINGLE",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "RELEASE_READY",
        "release_date": "2026-09-15",
        "tracklist": [
            {
                "track_number": 1,
                "disc_number": 1,
                "astrazit_recording_id": "AST-REC-000001",
            }
        ],
        "artwork": [
            {
                "asset_id": "demo-art-rel-000001",
                "asset_type": "COVER_ART",
                "uri": "file:///demo-storage/AST-REL-000001/cover_3000x3000.png",
                "mime_type": "image/png",
            }
        ],
        "distribution": [
            {
                "provider": "distrokid",
                "external_release_id": "DEMO-DK-REL-001",
                "status": "SUBMITTED",
            }
        ],
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-01T12:00:00Z",
            "approval_status": "APPROVED",
            "approver": "demo-release-admin",
            "approved_at": "2026-09-01T12:30:00Z",
            "version": 1,
            "canonical_status": "MASTER_METADATA",
            "notes": "DEMO FIXTURE: Non-production release package for Electric Dream.",
        },
    },
    # 2. Beat in Your Veins - Single (Native, Draft, contains Recording 3)
    {
        "schema_version": "1.0.0",
        "astrazit_release_id": "AST-REL-000002",
        "title": "Beat in Your Veins - Single",
        "artist": "AstraZit",
        "release_type": "SINGLE",
        "catalog_origin": "NATIVE",
        "lifecycle_status": "DRAFT",
        "tracklist": [
            {
                "track_number": 1,
                "disc_number": 1,
                "astrazit_recording_id": "AST-REC-000003",
            }
        ],
        "distribution": [
            {
                "provider": "distrokid",
                "external_release_id": "DEMO-DK-REL-002",
                "status": "DRAFT",
            }
        ],
        "provenance": {
            "source": "HUMAN_ENTERED",
            "source_system": "demo_catalog_fixture",
            "generated_at": "2026-09-02T12:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Draft release for Beat in Your Veins.",
        },
    },
    # 3. Creatures of the Night - Single (Historical Import, Released, contains Recording 4 & 5)
    {
        "schema_version": "1.0.0",
        "astrazit_release_id": "AST-REL-000003",
        "title": "Creatures of the Night",
        "artist": "AstraZit",
        "release_type": "SINGLE",
        "catalog_origin": "HISTORICAL_IMPORT",
        "lifecycle_status": "RELEASED",
        "release_date": "2024-06-01",
        "tracklist": [
            {
                "track_number": 1,
                "disc_number": 1,
                "astrazit_recording_id": "AST-REC-000004",
            },
            {
                "track_number": 2,
                "disc_number": 1,
                "astrazit_recording_id": "AST-REC-000005",
            },
        ],
        "distribution": [
            {
                "provider": "distrokid",
                "external_release_id": "DEMO-DK-REL-003",
                "status": "LIVE",
            }
        ],
        "provenance": {
            "source": "IMPORTED",
            "source_system": "legacy_demo_import",
            "generated_at": "2024-06-01T00:00:00Z",
            "approval_status": "PENDING_APPROVAL",
            "version": 1,
            "canonical_status": "PROVISIONAL",
            "notes": "DEMO FIXTURE: Historical release package for Creatures of the Night.",
        },
        "historical_import": {
            "first_released_at": "2024-06-01T00:00:00Z",
            "imported_at": "2026-09-01T00:00:00Z",
            "source_reference": "https://demo.astrazit.local/legacy-import/creatures-rel",
            "rights_review_required": True,
        },
    },
]


def get_all_demo_fixtures() -> dict[str, list[dict[str, Any]]]:
    """Return a detached deep copy of all demo fixtures."""
    return {
        "works": copy.deepcopy(WORK_FIXTURES),
        "recordings": copy.deepcopy(RECORDING_FIXTURES),
        "releases": copy.deepcopy(RELEASE_FIXTURES),
    }
