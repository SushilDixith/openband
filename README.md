# ((●)) OPENBAND — A Movement for Free Media

```text
   ╭───╮ ┌───╮ ┌───╴ ┌─╮ ╷ ┌───╮ ╭───╮ ┌─╮ ╷ ┌───╮ 
   │   │ ├───╯ ├───╴ │ │ │ ├───┤ ├───┤ │ │ │ │   │ 
   ╰───╯ │     └───╴ ╵ ╰─╯ └───╯ │   │ ╵ ╰─╯ └───╯
 A MOVEMENT FOR FREE MEDIA  ·  YOUR MEDIA. YOUR TERMS.
```

**OpenBand** is an open-signal, archival multi-platform terminal interface (`TUI`) built around a larger idea: **putting media access, portability, and long-term stewardship back into the hands of the people who experience it.**

It unites `yt-dlp`, `ffmpeg`, and an API-key-free Spotify/social resolver inside a high-contrast editorial interface inspired by independent print publishing, underground zines, and public-interest archives.

---

## 1. One-Command Installation & Quick Start

### Install Globally as a Command-Line Tool (`pipx` / `uv` / `pip`)

```bash
# Recommended: isolated global CLI install via pipx or uv
pipx install .
# or:
uv tool install .
# or editable development install:
pip install -e .
```

Once installed, launch OpenBand from any directory:

```bash
openband                                      # Full cinematic launch
openband --fast                               # Skip opening sequence (or set OPENBAND_NO_SPLASH=1)
openband https://youtu.be/dQw4w9WgXcQ -p 2    # Launch & immediately archive URL with Preset 2
openband --batch-file urls.txt -p 3           # Enqueue an entire file of URLs as 320kbps MP3s
openband --export-catalog                     # Export local Commons Catalog to .m3u8, .md, and .csv
```

### System Dependencies (`F1` in-app checks status)
- **`ffmpeg`** *(strongly recommended)*: Required for merging 1080p/4K video+audio streams, audio conversion (`MP3`, `M4A`, `FLAC`, `WAV`), time-range clipping, chapter splitting, and Archival Bundles.
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
- **`deno` or `node`** *(recommended)*: Solves JavaScript challenges on YouTube and social platforms.

---

## 2. Terminal Interface Preview (Operational Desk)

```text
((●)) O P E N B A N D  ·  YOUR MEDIA. YOUR TERMS.      YT-DLP 2026.x · FFMPEG ● OK · JS ● DENO · PLATFORMS ● YT·IG·X·FB·SP
▸ Welcome to OpenBand, operator  ·  good evening (session #4)  ·  LESS LOCK-IN. MORE FREEDOM.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
╭─ ((●)) SIGNAL ACQUISITION DESK ──────────────────────────╮  ╭─ ((●)) PLATE 02/06 · THE OPEN SPAN ──────────────────────╮
│ URL       https://www.instagram.com/reel/C8abc123_/      │  │          +                .___.        .___.             │
│ OUT       ~/Archive/Commons                              │  │               .|.         |III|________|III|             │
│                                                          │  │              |:::|       /|===|[======]|===|\            │
│ SCOPE     (•) SINGLE   ( ) PLAYLIST  [X] ARCHIVE [ ] SPLIT│  │        .__.  |:::|      / |   |        |   | \           │
│ MODE      (•) VIDEO    ( ) AUDIO                         │  │     .__|::|__|:::|_____/  |   |        |   |             │
│ VIDEO     [H.264 ▾]    RES [1080P ▾] [ ] 60FPS           │  │   ==|::|::|::|:::|====/===|===|========|===|==           │
│                                                          │  │     ~~~~~~~~~~~~~~~~~/~~~~|~~~|~~~~~~~~|~~~|~~           │
│ ▸ F7  subs · cookies · range · limit · proxy  · Alt+1..4 │  │   "The internet was built to connect, not to exclude."   │
╰──────────────────────────────── DETECTED: INSTAGRAM · REEL╯  ╰─────────────────────────── LESS LOCK-IN. MORE FREEDOM. ──╯
╭─ OUTPUT PREVIEW ─────────────────────────────────────────╮  ╭─ FIELD GUIDE ────────────────────────────────────────────╮
│ Behind the scenes (OpenBand Collective (@openband) · 0:42│  │ INSTAGRAM LINK · REEL / POST / STORY                     │
│ ▸ MP4 · H.264 · 1080p · 30fps  +  AAC  [+ARCHIVE]        │  │ Supports public Reels, video posts & authorized Stories. │
│   ≈ 14 MB  ·  plays: everything                          │  │ $ yt-dlp --no-playlist -f 'bv*[height<=1080]...'         │
╰──────────────────────────────── SCANNED (INSTAGRAM) · F3 ╯  ╰─────────────────────────────────── TOPIC: URL · F10 CLI ─╯
SIGNAL    ▐████████████████████████████░░░░░░░░░░▌  72%  ((●)) 1/1  4.8 MiB/s
╭─ TRANSMISSION & ARCHIVE LOG ───────────────────────────────────────────────────────────────────────────────────────────╮
│ ✓ [INSTAGRAM] Behind the scenes at the archive                                                                         │
│ · creator: OpenBand Collective (@openband.collective)   ·   source: https://www.instagram.com/reel/C8abc123_/          │
│ ✓ archived · 1 file · 14 MB · user-owned copy                                                                          │
│ · provenance sidecar saved: Behind the scenes at the archive.nfo                                                       │
╰─────────────────────────────────────────────────────────────────────────────────────────────────── REAL-TIME TELEMETRY ╯
 F2 SCAN  F3 FORMATS  F4 CATALOG  F5 DOWNLOAD  ESC CANCEL  F6 OPEN  F7 OPTIONS  F8 PLATE  F10 CLI  ^G PASTE  ^B BATCH  ^Q
```

---

## 3. Supported Platforms & Archival Capabilities

| Platform | Supported Media Types | Automatic Behavior & Archival Features |
| :--- | :--- | :--- |
| **YouTube** | Videos, Shorts, Playlists, Live streams, Clips | Full codec selection (`AV1`, `VP9`, `H.265`, `H.264`), `60FPS` toggle, Chapter Splitter (`SPLIT`), Subtitle & Clean `.transcript.txt` Harvester, Time-Range Clipper. |
| **Spotify** | Tracks, Albums, Playlists, Podcast Episodes & Shows | Resolves metadata without API keys via public embeds/oEmbed; switches to `AUDIO` mode automatically; downloads full-length audio (`>65s` filter rejects 30s snippets/Shorts) with two-pass retry recovery and ID3 tagging. |
| **Instagram** | Reels (`/reel/`), Posts & Carousels (`/p/`), IGTV (`/tv/`), Stories (`/stories/`) | Automatic creator `@handle` attribution; muxed/DASH MP4 stream selection; flags Stories when browser cookies (`F7 → COOKIES`) are required. |
| **X (Twitter)** | Video Statuses (`/status/`), Multi-video posts, Broadcasts, Audio Spaces (`/i/spaces/`) | Normalizes `vxtwitter.com` / `fxtwitter.com` / `fixupx.com` links to `x.com`; switches X Spaces automatically to `AUDIO` mode. |
| **Facebook** | Facebook Watch (`fb.watch`, `/watch/?v=`), Reels (`/reel/`), Public & Page Videos (`/videos/`, `/share/v/`) | Handles SD/HD MP4 & DASH streams even when GraphQL omits `vcodec`/height metadata; supports authenticated videos via `F7 → COOKIES`. |

---

## 4. Deeper Archival & Local Library Stewardship

OpenBand is designed not just to download files, but to build a **self-contained, portable personal library**:

1. **Archival Bundle (`[X] ARCHIVE` or `Alt+2`)**:
   - Embeds creator metadata, upload date, chapter markers, cover thumbnail, and subtitles directly inside the media container.
   - Automatically writes a **Kodi / Jellyfin / Plex XML provenance sidecar (`.nfo`)** alongside the media file containing the title, creator, studio/platform, release date, and original `uniqueid` source URL.
2. **Clean Plain-Text Transcript Harvester (`SUBS → CLEAN TXT`)**:
   - Downloads WebVTT/SRT captions and strips timestamps, inline HTML tags, and rolling duplicates into a clean `.transcript.txt` file for offline reading and research.
   - Press **`T`** on any item inside the **`F4` Commons Catalog** to open the **Offline Transcript Reader** with live keyword highlighting.
3. **Portable Commons Catalog Exports (`F4 → press E` or `openband --export-catalog`)**:
   - Exports your local archive (`~/.openband_catalog.json`) into three open formats in your home directory:
     - `~/openband_catalog.m3u8` — Extended M3U playlist ready for VLC, mpv, Jellyfin, or Navidrome.
     - `~/openband_catalog.md` — Formatted Markdown ledger with total disk footprint and source links.
     - `~/openband_catalog.csv` — Standard UTF-8 CSV spreadsheet.
4. **Batch URL Importer (`Ctrl+B` or `--batch-file`)**:
   - Paste a multi-line list of URLs (or load a `.txt` / `.md` file with `#` comments) to validate and enqueue mixed YouTube, Spotify, Instagram, X, and Facebook jobs in one step.

---

## 5. Keyboard Shortcuts & Presets

| Key | Action |
| :--- | :--- |
| `ENTER` / `F5` | Start download immediately (or append to non-blocking queue if busy) |
| `F2` | Scan URL to inspect real formats, codecs, bitrates, tracks & creator metadata |
| `F3` | Open interactive **Format & Codec Inspector** table |
| `F4` | Open searchable **Commons Catalog** (`ENTER` play, `T` read transcript, `E` export M3U8/MD/CSV, `O` open folder, `U` load URL) |
| `Ctrl+B` | Open **Batch Signal Importer** (paste multi-line URLs or load a `.txt`/`.md` list) |
| `Ctrl+G` | Paste from system clipboard & scan (opens Batch Importer automatically if clipboard has multiple URLs) |
| `F6` | Open output directory in system file manager |
| `F7` | Toggle advanced options (`NAME` template, `SUBS`, browser `COOKIES`, time `RANGE`, speed `LIMIT`, `PROXY`) |
| `F8` | Cycle monochrome artwork plate & manifesto quote |
| `F10` | Copy live equivalent `yt-dlp` / `spotdl` CLI command to clipboard |
| `Alt+1` .. `Alt+4` | Apply built-in presets (`Alt+1` TV-Safe 1080p MP4, `Alt+2` Full Archive Bundle, `Alt+3` 320k MP3, `Alt+4` Lossless FLAC) |
| `F9` / `F1` | Update `yt-dlp` (`F9`) / Run environment & extractor diagnostics (`F1`) |
| `ESC` / `Ctrl+Q` | Cancel active/queued jobs (`ESC`) / Quit with session sign-off banner (`Ctrl+Q`) |

---

*Your media. Your terms. Less lock-in. More freedom.*
