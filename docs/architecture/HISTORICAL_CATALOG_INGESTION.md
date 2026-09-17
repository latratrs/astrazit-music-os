# AstraZit Music OS — Historical Catalog Ingestion Staging

## 1. Purpose

OS-010 prepares the 139-song historical catalog for later canonical import without
allocating AST identifiers, writing catalog records, asserting rights, clearing a
recording for radio, or modifying source audio. It is a deterministic review layer
between an external CSV/audio library and the governed Music OS repository.

The output is evidence for a human decision, not database truth.

## 2. Safety boundary

The staging command:

- opens the catalog CSV and WAV masters read-only;
- writes only a generated manifest under `.local/catalog/import-staging/` by default;
- rejects report or manifest paths that could overwrite an input, audio tool, source
  WAV, derivative WAV, or deterministic intermediate output;
- never invokes `IdentifierAllocator`, `SequenceStore`, or `CatalogRepository`;
- leaves Work, Recording, and Release AST IDs null and explicitly unallocated;
- leaves composition rights, master rights, metadata approval, and radio clearance unresolved;
- never moves, renames, normalizes, transcodes, or deletes a master;
- never creates a radio derivative;
- never guesses a WAV association from a filename.

WAV association requires an explicit two-column map:

```csv
source_row,wav_path
2,D:\AstraZit Masters\Example.wav
```

`source_row` is the physical CSV row number, including the header as row 1. This
allows same-title releases to remain separate until a human disambiguates them.

## 3. Source CSV contract

The columns are intentionally closed and ordered:

```text
song,listeners,streams,saves,release_date,exact_music_genre,radio_daypart,genre_description
```

Release dates use explicit `M/D/YYYY` interpretation and are normalized to ISO date
strings only inside the staging manifest. Titles and descriptive text are preserved.
No spelling correction or title merging occurs automatically.

The source file SHA-256 plus row number creates an audit locator such as
`SHA256:<digest>:ROW:2`. This locator is not an identity and must never influence AST
ID allocation.

## 4. Metadata and programming status

Genre, genre description, daypart, representative-track selection, and rotation
inputs remain `PROVISIONAL`. Streams are retained as an input, but OS-010 assigns no
rotation tier. A candidate for each frozen daypart is selected deterministically by
highest source stream count, title comparison, then source row. Selection does not
mean radio clearance.

Frozen staging keys are `SUNRISE`, `DAY`, `FUTURE`, `SUNSET`, `NIGHT`, and
`DEEP_SPACE`, matching the source schedule. They remain proposed radio metadata until
human promotion through a future governed service.

## 5. Audio QC

Basic inspection uses Python's WAV reader and supports uncompressed 8-, 16-, 24-,
and 32-bit integer PCM. It records:

- source SHA-256 and byte size;
- codec description, sample rate, bit depth, channels, frames, and duration;
- sample peak and exact stored PCM ceiling-sample count;
- short-duration and clipping review warnings.

When explicitly available, `ffprobe` verifies the first audio stream and `ffmpeg`
performs EBU loudness analysis. The provisional broadcast target is approximately
`-14 LUFS` with true peak no higher than `-1 dBTP`. A source outside those bounds is
not rejected as a master; it is marked as needing a separate radio derivative.

If loudness tooling is unavailable, analysis remains `BASIC_ONLY`,
`audio_qc_pass=false`, and `radio_derivative_required=null`. The system does not guess.

Resumable full-catalog QC and derivative runs re-hash source WAV bytes before
accepting completed checkpoint rows. An unchanged CSV map is not sufficient proof
that the mapped audio is unchanged.

## 6. Readiness gates

Every staged row separately reports:

```text
master_present
master_valid
audio_qc_pass
radio_derivative_required
rights_verified
radio_cleared
metadata_approved
ready_for_radio
```

OS-010 never sets rights, clearance, metadata approval, or final readiness to true.
A future human-approved import service must verify every prerequisite explicitly.

## 7. Usage

```powershell
.venv\Scripts\python.exe scripts\prepare_catalog_import.py <catalog.csv>
```

With explicit WAV mapping and audio tools:

```powershell
.venv\Scripts\python.exe scripts\prepare_catalog_import.py <catalog.csv> `
  --wav-map <wav-map.csv> --ffprobe <ffprobe.exe> --ffmpeg <ffmpeg.exe>
```

The command fails closed on column drift, malformed values, unknown dayparts,
ambiguous WAV-map rows, invalid WAV files, or analysis failure.

## 8. Deferred canonical import

Canonical persistence belongs to a later gated ticket. Before it can run, a human
must provide or approve Work composition contributors, Recording master owners,
artist/version disambiguation, release relationships, historical-release evidence,
radio curation, and the production identifier authority. AST identifiers are then
allocated only through the approved authority and records are written in dependency
order: Work, Recording, Release.
