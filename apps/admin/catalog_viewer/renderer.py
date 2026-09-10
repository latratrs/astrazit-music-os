"""HTML rendering utilities and templates for AstraZit Music OS catalog viewer.

Governed by OS-008.
Uses pure Python standard library html string generation with strict HTML escaping.
Guarantees:
- Never renders internal AST fixture IDs.
- Automatically escapes user/catalog data.
- High contrast, dark studio visual theme.
- Persistent non-production DEMO badge.
"""
from __future__ import annotations

import html
from typing import Any, Optional

from apps.admin.catalog_viewer.view_models import (
    CatalogSummaryView,
    LinkedItem,
    ProvenanceView,
    RecordingDetailView,
    RecordingListItem,
    ReleaseDetailView,
    ReleaseListItem,
    WorkDetailView,
    WorkListItem,
)


def h(val: Any) -> str:
    """Safely escape text for HTML output."""
    if val is None:
        return ""
    return html.escape(str(val))


def render_badge(status: Optional[str]) -> str:
    """Render a styled badge for status values."""
    if not status:
        return '<span class="badge">-</span>'
    cls = status.lower().replace(" ", "_").replace("-", "_")
    return f'<span class="badge {h(cls)}">{h(status)}</span>'


def render_layout(title: str, content: str, active_tab: str = "") -> str:
    """Render the master page layout."""
    nav_tabs = [
        ("Dashboard", "/admin/catalog", "dashboard"),
        ("Works", "/admin/catalog/works", "works"),
        ("Recordings", "/admin/catalog/recordings", "recordings"),
        ("Releases", "/admin/catalog/releases", "releases"),
    ]
    nav_html = []
    for label, url, key in nav_tabs:
        is_active = "active" if active_tab == key else ""
        nav_html.append(f'<a href="{url}" class="{is_active}">{label}</a>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{h(title)} — AstraZit Music OS</title>
  <link rel="stylesheet" href="/admin/catalog/static/catalog.css">
</head>
<body>
  <div class="demo-banner">
    <div>⚠️ <strong>DEMO / NON-PRODUCTION SANDBOX</strong> — Changes do not persist to production catalog</div>
    <div class="banner-tag">LOCAL EVALUATION ONLY</div>
  </div>
  <header class="navbar">
    <div class="brand">
      <span class="brand-title">AstraZit Music OS</span>
      <span class="brand-sub">LOCAL ADMIN · DEMO CATALOG</span>
    </div>
    <nav class="nav-links">
      {"".join(nav_html)}
    </nav>
  </header>
  <main class="container">
    {content}
  </main>
</body>
</html>
"""


def render_dashboard(summary: CatalogSummaryView) -> str:
    """Render the catalog summary dashboard."""
    val_badge = '<span class="badge active">VALID</span>' if summary.is_valid else '<span class="badge ineligible">ISSUES DETECTED</span>'

    comp_badges = "".join(
        f'<div style="margin-top: 4px;">{render_badge(st)} <span class="mono">{count}</span></div>'
        for st, count in summary.composition_rights_counts.items()
    )
    master_badges = "".join(
        f'<div style="margin-top: 4px;">{render_badge(st)} <span class="mono">{count}</span></div>'
        for st, count in summary.master_rights_counts.items()
    )
    rel_badges = "".join(
        f'<div style="margin-top: 4px;">{render_badge(st)} <span class="mono">{count}</span></div>'
        for st, count in summary.release_lifecycle_counts.items()
    )

    issues_html = ""
    if not summary.is_valid and summary.validation_issues:
        issues_list = "".join(f"<li>{h(issue)}</li>" for issue in summary.validation_issues)
        issues_html = f"""
        <div class="alert-box">
          <div class="alert-title">Sandbox Validation Issues</div>
          <ul style="padding-left: 20px; color: #fca5a5;">
            {issues_list}
          </ul>
        </div>
        """

    content = f"""
    <div class="page-header">
      <div>
        <h1 class="page-title">Catalog Overview</h1>
        <div class="page-subtitle">Sandbox Environment: {h(summary.sandbox_path_display)} &bull; State: {val_badge}</div>
      </div>
      <div class="quick-links">
        <a href="/admin/catalog/works" class="btn">View Works</a>
        <a href="/admin/catalog/recordings" class="btn">View Recordings</a>
        <a href="/admin/catalog/releases" class="btn">View Releases</a>
      </div>
    </div>

    {issues_html}

    <div class="cards-grid">
      <div class="card">
        <div class="card-title">Musical Works</div>
        <div class="card-stat mono">{summary.works_count}</div>
        <div class="card-desc">Authoritative underlying compositions</div>
      </div>
      <div class="card">
        <div class="card-title">Sound Recordings</div>
        <div class="card-stat mono">{summary.recordings_count}</div>
        <div class="card-desc">Audio cuts, masters & radio assets</div>
      </div>
      <div class="card">
        <div class="card-title">Releases</div>
        <div class="card-stat mono">{summary.releases_count}</div>
        <div class="card-desc">Singles, EPs & commercial packages</div>
      </div>
      <div class="card">
        <div class="card-title">Radio Playout Status</div>
        <div class="card-stat mono" style="font-size: 20px;">
          <span style="color: #6ee7b7;">{summary.radio_eligible_count} Eligible</span> /
          <span style="color: #fca5a5;">{summary.radio_ineligible_count} Ineligible</span>
        </div>
        <div class="card-desc">Playout-ready broadcast rotation tracks</div>
      </div>
    </div>

    <div class="cards-grid">
      <div class="card">
        <div class="card-title">Composition Rights Status</div>
        {comp_badges}
      </div>
      <div class="card">
        <div class="card-title">Master Rights Status</div>
        {master_badges}
      </div>
      <div class="card">
        <div class="card-title">Release Lifecycles</div>
        {rel_badges}
      </div>
    </div>
    """
    return render_layout("Dashboard", content, active_tab="dashboard")


def render_works_list(works: list[WorkListItem]) -> str:
    """Render the list of musical works."""
    rows = []
    for w in works:
        rows.append(f"""
        <tr>
          <td class="mono"><a href="{w.detail_url}">{h(w.demo_id)}</a></td>
          <td><strong><a href="{w.detail_url}">{h(w.canonical_title)}</a></strong></td>
          <td>{render_badge(w.catalog_origin)}</td>
          <td>{render_badge(w.lifecycle_status)}</td>
          <td>{render_badge(w.composition_rights_status)}</td>
          <td class="mono">{w.writers_count}</td>
          <td class="mono">{w.linked_recordings_count}</td>
          <td><a href="{w.detail_url}">View Details &rarr;</a></td>
        </tr>
        """)

    content = f"""
    <div class="page-header">
      <div>
        <h1 class="page-title">Musical Works</h1>
        <div class="page-subtitle">Canonical compositions and publishing ownership ({len(works)} total)</div>
      </div>
    </div>

    <div class="section">
      <div class="data-table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>Demo ID</th>
              <th>Canonical Title</th>
              <th>Origin</th>
              <th>Lifecycle</th>
              <th>Composition Rights</th>
              <th>Writers</th>
              <th>Recordings</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """
    return render_layout("Works", content, active_tab="works")


def render_provenance_block(prov: Optional[ProvenanceView]) -> str:
    if not prov:
        return "<p style='color: var(--text-muted);'>No provenance record available.</p>"
    return f"""
    <div class="kv-grid">
      <div class="kv-item">
        <div class="kv-label">Source</div>
        <div class="kv-value">{h(prov.source)} ({h(prov.source_system)})</div>
      </div>
      <div class="kv-item">
        <div class="kv-label">Approval Status</div>
        <div class="kv-value">{render_badge(prov.approval_status)}</div>
      </div>
      <div class="kv-item">
        <div class="kv-label">Approver</div>
        <div class="kv-value">{h(prov.approver or "-")}</div>
      </div>
      <div class="kv-item">
        <div class="kv-label">Generated At</div>
        <div class="kv-value mono" style="font-size: 12px;">{h(prov.generated_at)}</div>
      </div>
      <div class="kv-item">
        <div class="kv-label">Canonical Status</div>
        <div class="kv-value">{render_badge(prov.canonical_status)}</div>
      </div>
      <div class="kv-item">
        <div class="kv-label">Notes</div>
        <div class="kv-value">{h(prov.notes or "-")}</div>
      </div>
    </div>
    """


def render_work_detail(work: WorkDetailView) -> str:
    """Render detailed view of a musical work."""
    writers_rows = "".join(
        f"<tr><td>{h(w.name)}</td><td>{h(w.role)}</td><td class='mono'>{w.percentage:.1f}%</td></tr>"
        for w in work.writers
    )
    publishers_rows = "".join(
        f"<tr><td>{h(p.name)}</td><td>{h(p.role)}</td><td class='mono'>{p.percentage:.1f}%</td></tr>"
        for p in work.publishers
    )

    recs_rows = []
    for r in work.linked_recordings:
        recs_rows.append(f"""
        <li class="linked-item">
          <div class="linked-main">
            <span class="mono"><a href="{r.url}">{h(r.demo_id)}</a></span>
            <strong><a href="{r.url}">{h(r.title)}</a></strong>
            <span class="linked-sub">{h(r.subtitle)}</span>
          </div>
          <div>{render_badge(r.badge)}</div>
        </li>
        """)
    if not recs_rows:
        recs_html = "<div style='padding: 16px; color: var(--text-muted);'>No recordings linked to this work.</div>"
    else:
        recs_html = f'<ul class="linked-list">{"".join(recs_rows)}</ul>'

    content = f"""
    <div class="page-header">
      <div>
        <div class="page-subtitle"><a href="/admin/catalog/works">&larr; Back to Works</a></div>
        <h1 class="page-title">{h(work.canonical_title)}</h1>
        <div class="page-subtitle mono">{h(work.demo_id)}</div>
      </div>
      <div>
        {render_badge(work.lifecycle_status)}
        {render_badge(work.composition_rights_status)}
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">Work Attributes</span>
      </div>
      <div class="section-body">
        <div class="kv-grid">
          <div class="kv-item">
            <div class="kv-label">Demo Identifier</div>
            <div class="kv-value mono">{h(work.demo_id)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Canonical Title</div>
            <div class="kv-value">{h(work.canonical_title)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Catalog Origin</div>
            <div class="kv-value">{render_badge(work.catalog_origin)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Lifecycle Status</div>
            <div class="kv-value">{render_badge(work.lifecycle_status)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Composition Rights</div>
            <div class="kv-value">{render_badge(work.composition_rights_status)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Copyright Notice</div>
            <div class="kv-value">{h(work.copyright_notice or "-")}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="cards-grid" style="grid-template-columns: 1fr 1fr;">
      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Writers & Composers</span></div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>Name</th><th>Role</th><th>Split</th></tr></thead>
            <tbody>{writers_rows}</tbody>
          </table>
        </div>
      </div>
      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Publishers</span></div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>Name</th><th>Role</th><th>Split</th></tr></thead>
            <tbody>{publishers_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="section" style="margin-top: 24px;">
      <div class="section-header">
        <span class="section-title">Linked Sound Recordings ({len(work.linked_recordings)})</span>
      </div>
      {recs_html}
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">Provenance</span></div>
      <div class="section-body">{render_provenance_block(work.provenance)}</div>
    </div>
    """
    return render_layout(f"Work — {work.canonical_title}", content, active_tab="works")


def render_recordings_list(recordings: list[RecordingListItem]) -> str:
    """Render list of sound recordings."""
    rows = []
    for r in recordings:
        radio_badge = render_badge("ELIGIBLE") if r.radio_eligible else render_badge("INELIGIBLE")
        rows.append(f"""
        <tr>
          <td class="mono"><a href="{r.detail_url}">{h(r.demo_id)}</a></td>
          <td><strong><a href="{r.detail_url}">{h(r.display_title)}</a></strong></td>
          <td><a href="{r.work_url}" class="mono">{h(r.work_demo_id)}</a><br><small>{h(r.work_title)}</small></td>
          <td>{render_badge(r.lifecycle_status)}</td>
          <td>{render_badge(r.master_rights_status)}</td>
          <td>{radio_badge}</td>
          <td>{render_badge(r.rotation_tier)}</td>
          <td class="mono">{h(r.duration_formatted)}</td>
          <td>{h(r.bpm_key_display)}</td>
          <td><a href="{r.detail_url}">View Details &rarr;</a></td>
        </tr>
        """)

    content = f"""
    <div class="page-header">
      <div>
        <h1 class="page-title">Sound Recordings</h1>
        <div class="page-subtitle">Audio masters, stems, and radio rotation tracks ({len(recordings)} total)</div>
      </div>
    </div>

    <div class="section">
      <div class="data-table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>Demo ID</th>
              <th>Title / Version</th>
              <th>Linked Work</th>
              <th>Lifecycle</th>
              <th>Master Rights</th>
              <th>Radio Eligibility</th>
              <th>Rotation</th>
              <th>Duration</th>
              <th>BPM / Key</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """
    return render_layout("Recordings", content, active_tab="recordings")


def render_recording_detail(rec: RecordingDetailView) -> str:
    """Render detailed view of a sound recording."""
    radio_badge = render_badge("ELIGIBLE") if rec.radio_eligible else render_badge("INELIGIBLE")

    owners_rows = "".join(
        f"<tr><td>{h(o.name)}</td><td>{h(o.role)}</td><td class='mono'>{o.percentage:.1f}%</td></tr>"
        for o in rec.owners
    )

    releases_rows = []
    for rel in rec.linked_releases:
        releases_rows.append(f"""
        <li class="linked-item">
          <div class="linked-main">
            <span class="mono"><a href="{rel.url}">{h(rel.demo_id)}</a></span>
            <strong><a href="{rel.url}">{h(rel.title)}</a></strong>
            <span class="linked-sub">{h(rel.subtitle)}</span>
          </div>
          <div>{render_badge(rel.badge)}</div>
        </li>
        """)
    if not releases_rows:
        releases_html = "<div style='padding: 16px; color: var(--text-muted);'>No releases contain this recording.</div>"
    else:
        releases_html = f'<ul class="linked-list">{"".join(releases_rows)}</ul>'

    dayparts = ", ".join(rec.daypart_candidates) if rec.daypart_candidates else "-"
    moods = ", ".join(rec.moods) if rec.moods else "-"
    subgenres = ", ".join(rec.subgenres) if rec.subgenres else "-"

    content = f"""
    <div class="page-header">
      <div>
        <div class="page-subtitle"><a href="/admin/catalog/recordings">&larr; Back to Recordings</a></div>
        <h1 class="page-title">{h(rec.display_title)}</h1>
        <div class="page-subtitle">Artist: {h(rec.artist)} &bull; ID: <span class="mono">{h(rec.demo_id)}</span></div>
      </div>
      <div>
        {render_badge(rec.lifecycle_status)}
        {render_badge(rec.master_rights_status)}
      </div>
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">Recording Identity & Composition Link</span></div>
      <div class="section-body">
        <div class="kv-grid">
          <div class="kv-item">
            <div class="kv-label">Demo Identifier</div>
            <div class="kv-value mono">{h(rec.demo_id)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Linked Work</div>
            <div class="kv-value">
              <a href="{rec.work_url}" class="mono">{h(rec.work_demo_id)}</a> &mdash; {h(rec.work_title)}
            </div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Artist</div>
            <div class="kv-value">{h(rec.artist)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Catalog Origin</div>
            <div class="kv-value">{render_badge(rec.catalog_origin)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Lifecycle Status</div>
            <div class="kv-value">{render_badge(rec.lifecycle_status)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Master Rights</div>
            <div class="kv-value">{render_badge(rec.master_rights_status)}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="cards-grid" style="grid-template-columns: 1fr 1fr;">
      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Radio Playout & Rotation</span></div>
        <div class="section-body">
          <div class="kv-grid">
            <div class="kv-item">
              <div class="kv-label">Eligibility</div>
              <div class="kv-value">{radio_badge} ({h(rec.radio_eligibility_status)})</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">Rotation Tier</div>
              <div class="kv-value">{render_badge(rec.rotation_tier)}</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">Daypart Candidates</div>
              <div class="kv-value">{h(dayparts)}</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">Programming Notes</div>
              <div class="kv-value">{h(rec.radio_programming_notes or "-")}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Audio & Musical Metadata</span></div>
        <div class="section-body">
          <div class="kv-grid">
            <div class="kv-item">
              <div class="kv-label">Duration</div>
              <div class="kv-value mono">{h(rec.duration_formatted)}</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">BPM / Key</div>
              <div class="kv-value">{f"{rec.bpm:g} BPM" if rec.bpm else "-"} &bull; {h(rec.key_scale)}</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">Genre</div>
              <div class="kv-value">{h(rec.genre)} ({h(subgenres)})</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">Moods</div>
              <div class="kv-value">{h(moods)}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="cards-grid" style="grid-template-columns: 1fr 1fr; margin-top: 24px;">
      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Master Rights & Ownership</span></div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>Owner</th><th>Role</th><th>Split</th></tr></thead>
            <tbody>{owners_rows}</tbody>
          </table>
        </div>
        <div style="padding: 12px 16px; border-top: 1px solid var(--border-color); font-size: 12px; color: var(--text-secondary);">
          Notice: {h(rec.copyright_notice or "-")}
        </div>
      </div>

      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Content ID & Registry State</span></div>
        <div class="section-body">
          <div class="kv-grid">
            <div class="kv-item">
              <div class="kv-label">YouTube Content ID</div>
              <div class="kv-value">{render_badge(rec.content_id_status or "EXCLUDED")}</div>
            </div>
            <div class="kv-item">
              <div class="kv-label">SoundExchange</div>
              <div class="kv-value">{render_badge(rec.soundexchange_status or "UNREGISTERED")}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="section" style="margin-top: 24px;">
      <div class="section-header">
        <span class="section-title">Releases Containing This Recording ({len(rec.linked_releases)})</span>
      </div>
      {releases_html}
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">Provenance</span></div>
      <div class="section-body">{render_provenance_block(rec.provenance)}</div>
    </div>
    """
    return render_layout(f"Recording — {rec.display_title}", content, active_tab="recordings")


def render_releases_list(releases: list[ReleaseListItem]) -> str:
    """Render list of commercial releases."""
    rows = []
    for r in releases:
        rows.append(f"""
        <tr>
          <td class="mono"><a href="{r.detail_url}">{h(r.demo_id)}</a></td>
          <td><strong><a href="{r.detail_url}">{h(r.title)}</a></strong></td>
          <td>{h(r.artist)}</td>
          <td>{render_badge(r.release_type)}</td>
          <td>{render_badge(r.catalog_origin)}</td>
          <td>{render_badge(r.lifecycle_status)}</td>
          <td class="mono">{h(r.release_date or "-")}</td>
          <td class="mono">{r.tracks_count}</td>
          <td><a href="{r.detail_url}">View Details &rarr;</a></td>
        </tr>
        """)

    content = f"""
    <div class="page-header">
      <div>
        <h1 class="page-title">Commercial Releases</h1>
        <div class="page-subtitle">Singles, EPs, Albums, and distribution packages ({len(releases)} total)</div>
      </div>
    </div>

    <div class="section">
      <div class="data-table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>Demo ID</th>
              <th>Title</th>
              <th>Artist</th>
              <th>Type</th>
              <th>Origin</th>
              <th>Lifecycle</th>
              <th>Release Date</th>
              <th>Tracks</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """
    return render_layout("Releases", content, active_tab="releases")


def render_release_detail(rel: ReleaseDetailView) -> str:
    """Render detailed view of a commercial release."""
    tracks_rows = []
    for t in rel.tracklist:
        tracks_rows.append(f"""
        <tr>
          <td class="mono">#{t.track_number}</td>
          <td class="mono"><a href="{t.recording_url}">{h(t.recording_demo_id)}</a></td>
          <td><strong><a href="{t.recording_url}">{h(t.recording_title)}</a></strong></td>
          <td class="mono">{h(t.duration_formatted)}</td>
          <td><a href="{t.recording_url}">View Recording &rarr;</a></td>
        </tr>
        """)

    dist_rows = "".join(
        f"<tr><td>{h(d.provider)}</td><td>{render_badge(d.status)}</td><td class='mono'>{h(d.external_release_id or '-')}</td></tr>"
        for d in rel.distribution
    )

    artwork_rows = "".join(
        f"<tr><td>{h(a.asset_type)}</td><td>{h(a.mime_type)}</td><td class='mono'>{h(a.asset_id)}</td></tr>"
        for a in rel.artwork_metadata
    )

    content = f"""
    <div class="page-header">
      <div>
        <div class="page-subtitle"><a href="/admin/catalog/releases">&larr; Back to Releases</a></div>
        <h1 class="page-title">{h(rel.title)}</h1>
        <div class="page-subtitle">Artist: {h(rel.artist)} &bull; ID: <span class="mono">{h(rel.demo_id)}</span></div>
      </div>
      <div>
        {render_badge(rel.lifecycle_status)}
        {render_badge(rel.release_type)}
      </div>
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">Release Metadata</span></div>
      <div class="section-body">
        <div class="kv-grid">
          <div class="kv-item">
            <div class="kv-label">Demo Identifier</div>
            <div class="kv-value mono">{h(rel.demo_id)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Title</div>
            <div class="kv-value">{h(rel.title)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Artist</div>
            <div class="kv-value">{h(rel.artist)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Release Type</div>
            <div class="kv-value">{render_badge(rel.release_type)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Catalog Origin</div>
            <div class="kv-value">{render_badge(rel.catalog_origin)}</div>
          </div>
          <div class="kv-item">
            <div class="kv-label">Release Date</div>
            <div class="kv-value mono">{h(rel.release_date or "-")}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">Tracklist ({len(rel.tracklist)})</span>
      </div>
      <div class="data-table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Recording Demo ID</th>
              <th>Track Title / Version</th>
              <th>Duration</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {"".join(tracks_rows)}
          </tbody>
        </table>
      </div>
    </div>

    <div class="cards-grid" style="grid-template-columns: 1fr 1fr;">
      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Distribution State</span></div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>Provider</th><th>Status</th><th>Demo Foreign ID</th></tr></thead>
            <tbody>{dist_rows or '<tr><td colspan="3">No distribution entries</td></tr>'}</tbody>
          </table>
        </div>
      </div>

      <div class="section" style="margin-bottom: 0;">
        <div class="section-header"><span class="section-title">Artwork Metadata</span></div>
        <div class="data-table-wrapper">
          <table class="data-table">
            <thead><tr><th>Asset Type</th><th>MIME Type</th><th>Asset ID</th></tr></thead>
            <tbody>{artwork_rows or '<tr><td colspan="3">No artwork entries</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="section" style="margin-top: 24px;">
      <div class="section-header"><span class="section-title">Provenance</span></div>
      <div class="section-body">{render_provenance_block(rel.provenance)}</div>
    </div>
    """
    return render_layout(f"Release — {rel.title}", content, active_tab="releases")


def render_error_page(status_code: int, message: str, resolution_hint: Optional[str] = None) -> str:
    """Render a clean error page without leaking Python tracebacks or paths."""
    hint_html = ""
    if resolution_hint:
        hint_html = f"""
        <div style="margin-top: 16px;">
          <strong>Suggested Action:</strong>
          <div class="code-block" style="margin-top: 8px;">{h(resolution_hint)}</div>
        </div>
        """

    content = f"""
    <div class="alert-box">
      <div class="alert-title">Error {status_code}: {h(message)}</div>
      <div class="alert-msg">
        The requested admin catalog operation could not be completed.
      </div>
      {hint_html}
      <div style="margin-top: 20px;">
        <a href="/admin/catalog" class="btn">&larr; Return to Catalog Dashboard</a>
      </div>
    </div>
    """
    return render_layout(f"Error {status_code}", content)
