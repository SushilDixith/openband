"""core — everything that talks to yt-dlp, platform detection, the local catalog, presets, or the system. No UI imports.

Kept free of Textual so it can be tested on its own (see tests/test_logic.py).
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
    from yt_dlp.version import __version__ as YTDLP_VERSION
except ModuleNotFoundError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]
    YTDLP_VERSION = "not-installed"

    class DownloadCancelled(Exception):  # type: ignore[no-redef]
        pass

from . import platforms, spotify

__all__ = [
    "YTDLP_VERSION", "DownloadCancelled", "CODEC_PATTERNS", "MP4_CODECS", "MERGE_CONTAINERS",
    "AUTO_ORDER", "BROWSERS", "SUBS_MODES", "PRESETS", "Preset",
    "clean", "YdlLogger", "DownloadOptions", "Diagnostics", "diagnose", "is_ffmpeg_installed",
    "FormatRow", "AudioFacts", "ScanData", "scan", "codec_family", "audio_family", "pick_row",
    "estimate_size", "build_video_format", "parse_rate_limit", "parse_time_seconds", "parse_time_range",
    "build_ydl_opts", "build_cli_command", "vtt_to_clean_text", "write_clean_transcripts",
    "CatalogEntry", "load_catalog", "append_catalog", "clear_catalog",
    "export_catalog_m3u8", "export_catalog_markdown", "export_catalog_csv",
    "write_provenance_nfo", "find_transcript_for_media",
    "parse_batch_urls", "load_batch_file",
    "load_presets", "read_clipboard", "copy_to_clipboard", "open_file",
    "make_progress_hook", "Got", "summarize_got", "Friendly", "friendly_error",
    "is_newer", "latest_ytdlp_version", "update_ytdlp", "count_playlist_entries",
    "open_folder", "setup_lines",
]

# ── codecs & constants ──────────────────────────────────────────────

# Matched against yt-dlp's `vcodec` (e.g. "avc1.640028", "vp09.00.40.08", "av01.0.08M.08").
CODEC_PATTERNS = {
    "h264": r"^(avc|h264)",
    "h265": r"^(hev|hvc|h265)",
    "vp9": r"^vp0?9",
    "av1": r"^(av01|av1)",
}
MP4_CODECS = ("h264", "h265")  # these go in MP4 (with AAC audio) so they play everywhere
MERGE_CONTAINERS = {"h264": "mp4", "h265": "mp4", "vp9": "mkv", "av1": "mkv"}

# yt-dlp's own preference when no codec is forced (see FormatSorter 'vcodec').
AUTO_ORDER = ["av1", "vp9", "h265", "h264", "other"]

BROWSERS = ("none", "firefox", "chrome", "brave", "edge", "safari", "chromium")
SUBS_MODES = ("off", "en", "all", "transcript")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def clean(text) -> str:
    stripped = ANSI_RE.sub("", str(text)).strip()
    return platforms.redact_secrets(stripped)


def codec_family(vcodec) -> Optional[str]:
    v = (vcodec or "").lower()
    if not v or v == "none":
        return None
    for key, pattern in CODEC_PATTERNS.items():
        if re.search(pattern, v):
            return key
    return "other"


def audio_family(acodec) -> Optional[str]:
    a = (acodec or "").lower()
    if not a or a == "none":
        return None
    if a.startswith(("mp4a", "aac")):
        return "AAC"
    if "opus" in a:
        return "Opus"
    if "vorbis" in a:
        return "Vorbis"
    if a.startswith("mp3"):
        return "MP3"
    if "flac" in a:
        return "FLAC"
    return a.split(".")[0].upper()


# ── logging ─────────────────────────────────────────────────────────

class YdlLogger:
    """yt-dlp logger that forwards sanitized messages to `sink(text, level)` (or drops them if None)."""

    def __init__(self, sink=None):
        self.sink = sink

    def _emit(self, msg, level="info"):
        if self.sink:
            self.sink(clean(msg), level)

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self._emit(msg)

    def info(self, msg):
        self._emit(msg)

    def warning(self, msg):
        self._emit(msg, "warn")

    def error(self, msg):
        self._emit(msg, "error")


# ── diagnostics ─────────────────────────────────────────────────────

JS_RUNTIMES = ("deno", "node", "bun", "qjs")


def is_ffmpeg_installed() -> bool:
    return shutil.which("ffmpeg") is not None


@dataclass(frozen=True)
class Diagnostics:
    ytdlp: str
    ffmpeg: bool
    js: Optional[str]  # name of the first JS runtime found, if any
    spotdl: bool = False


def diagnose() -> Diagnostics:
    js = next((name for name in JS_RUNTIMES if shutil.which(name)), None)
    return Diagnostics(YTDLP_VERSION, is_ffmpeg_installed(), js, spotify.is_spotdl_installed())


def setup_lines(d: Diagnostics) -> list[tuple[str, str]]:
    """(text, level) lines describing the environment and how to fix gaps."""
    system = platform.system()
    ffmpeg_cmd = {"Windows": "winget install Gyan.FFmpeg", "Darwin": "brew install ffmpeg"}.get(
        system, "sudo apt install ffmpeg"
    )
    deno_cmd = {
        "Windows": "winget install DenoLand.Deno",
        "Darwin": "brew install deno",
    }.get(system, "curl -fsSL https://deno.land/install.sh | sh")
    lines = [(f"yt-dlp {d.ytdlp}  — F9 updates it (powers YouTube, Instagram, X/Twitter, Facebook & 1000+ sites)", "note")]
    if d.ffmpeg:
        lines.append(("ffmpeg found — video+audio merging, clipping, chapters & archival bundling work", "ok"))
    else:
        lines.append(("ffmpeg missing — HD merging, clipping, and audio conversion are unavailable", "warn"))
        lines.append((f"  install: {ffmpeg_cmd}", "note"))
    if d.js:
        lines.append((f"JS runtime found ({d.js}) — YouTube & social platform challenges can be solved", "ok"))
    else:
        lines.append(("no JS runtime (deno / node) — some YouTube formats may be missing or return 403", "warn"))
        lines.append((f"  install: {deno_cmd}", "note"))
    if d.spotdl:
        lines.append(("spotdl found — Spotify songs, albums & playlists use direct spotdl engine", "ok"))
    else:
        lines.append(("Spotify ready — songs, playlists & podcasts resolve via OpenBand + yt-dlp (optional: pip install spotdl)", "ok"))
    for p_key in ("youtube", "instagram", "twitter", "facebook"):
        ok, msg = platforms.verify_extractor_support(p_key)
        lines.append((f"  extractor · {msg}", "ok" if ok else "warn"))
    if not (d.ffmpeg and d.js):
        lines.append(("restart OpenBand after installing so the new tools are found on PATH", "note"))
    return lines


# ── scanning ────────────────────────────────────────────────────────

def _apply_cookie_opts(opts: dict, cookies_from_browser: Optional[str]) -> None:
    """Configure browser or file cookies safely without logging sensitive credentials."""
    if cookies_from_browser and cookies_from_browser != "none":
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    else:
        cookie_file = os.environ.get("OPENBAND_COOKIES_FILE", "").strip()
        if cookie_file and os.path.isfile(cookie_file):
            opts["cookiefile"] = cookie_file


def _check_drm(info: dict) -> None:
    """Refuse DRM-protected streams explicitly without attempting bypass."""
    if info.get("drm") or info.get("_drm"):
        raise RuntimeError("This media is DRM-protected. OpenBand does not bypass DRM or technical access controls.")
    formats = info.get("formats") or []
    if formats and all(f.get("has_drm") or f.get("drm") for f in formats if isinstance(f, dict)):
        raise RuntimeError("This media is DRM-protected. OpenBand does not bypass DRM or technical access controls.")


def _extract(url, playlist=False, proxy=None, cookies_from_browser=None) -> dict:
    """Extract info for one media item. For playlists/carousels, resolves the first accessible entry."""
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed.")
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": not playlist,
        "playlist_items": "1",
        "logger": YdlLogger(),
    }
    if proxy:
        opts["proxy"] = proxy
    _apply_cookie_opts(opts, cookies_from_browser)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise RuntimeError("No information could be extracted.")
        _check_drm(info)
        entries = info.get("entries")
        if entries is None:
            return info
        entry = next((e for e in entries if isinstance(e, dict)), None)
        if entry is None:
            raise RuntimeError("This post or playlist has no accessible media entries.")
        _check_drm(entry)
        if not entry.get("formats") and not entry.get("url"):
            target = entry.get("webpage_url") or entry.get("url")
            if target:
                extracted = ydl.extract_info(target, download=False)
                if extracted:
                    _check_drm(extracted)
                    return extracted
        return entry


@dataclass(frozen=True)
class FormatRow:
    height: int
    fps: int            # bucketed: 30 or 60
    codec: str          # family key: h264 / h265 / vp9 / av1 / other
    vcodec: str         # raw codec string from the site
    ext: str            # source container as offered
    size: Optional[int] # bytes, approximate, video stream only
    has_audio: bool = False  # True if pre-merged (has both video and audio)


@dataclass(frozen=True)
class AudioFacts:
    size: Optional[int]
    abr: Optional[int]  # kbps
    codec: str          # "Opus", "AAC", ...


@dataclass
class ScanData:
    url: str
    title: str
    channel: str
    duration: Optional[int]  # seconds
    upload_date: str         # YYYY-MM-DD or ""
    rows: list
    audio: Optional[AudioFacts]
    spotify_data: Optional[spotify.SpotifyResolved] = None
    platform: str = "generic"
    media_kind: str = "video"
    webpage_url: str = ""
    has_chapters: bool = False
    has_subtitles: bool = False

    @property
    def heights(self) -> list:
        return sorted({r.height for r in self.rows}, reverse=True)

    @property
    def availability(self) -> dict:
        """codec family -> highest resolution offered."""
        best: dict = {}
        for r in self.rows:
            best[r.codec] = max(best.get(r.codec, 0), r.height)
        return best


def _size_of(fmt: dict, duration) -> Optional[int]:
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        return int(size)
    bitrate = fmt.get("tbr") or fmt.get("vbr") or fmt.get("abr")
    if bitrate and duration:
        return int(bitrate * 1000 / 8 * duration)
    return None


def summarize_formats(info: dict) -> list:
    """One row per (resolution, fps bucket, codec family), keeping the best stream of each.

    Also handles social-media streams (Instagram, X/Twitter, Facebook) where `vcodec` or `height`
    may be omitted on direct MP4/HLS formats.
    """
    duration = info.get("duration")
    groups: dict = {}
    for f in info.get("formats") or []:
        family = codec_family(f.get("vcodec"))
        height = f.get("height")
        if not family or not height:
            continue
        bucket = 60 if (f.get("fps") or 30) >= 50 else 30
        key = (height, bucket, family)
        score = f.get("vbr") or f.get("tbr") or 0
        old_score = (groups[key].get("vbr") or groups[key].get("tbr") or 0) if key in groups else -1
        if key not in groups or score > old_score:
            groups[key] = f

    # Fallback for social-media extractors (Instagram, X, Facebook) that omit vcodec or height on valid video streams
    if not groups:
        for f in info.get("formats") or []:
            vcodec_raw = str(f.get("vcodec") or "").lower()
            ext_raw = str(f.get("ext") or "").lower()
            if vcodec_raw == "none":
                continue
            if ext_raw in ("mhtml", "jpg", "jpeg", "png", "webp", "vtt", "srt", "json"):
                continue
            height = f.get("height")
            if not height:
                fmt_id = str(f.get("format_id") or "").lower()
                if "hd" in fmt_id or "1080" in fmt_id or "720" in fmt_id:
                    height = 720
                elif "sd" in fmt_id or ext_raw in ("mp4", "mov", "webm"):
                    height = 480
            if not height:
                continue
            family = codec_family(vcodec_raw) or ("h264" if ext_raw in ("mp4", "mov") else "other")
            bucket = 60 if (f.get("fps") or 30) >= 50 else 30
            key = (int(height), bucket, family)
            score = f.get("vbr") or f.get("tbr") or 0
            old_score = (groups[key].get("vbr") or groups[key].get("tbr") or 0) if key in groups else -1
            if key not in groups or score > old_score:
                groups[key] = f

    # Direct single-URL fallback when info itself is a direct video item without a `formats` list
    if not groups and info.get("url") and str(info.get("ext") or "").lower() in ("mp4", "mov", "webm", "mkv"):
        h = int(info.get("height") or 720)
        fam = codec_family(info.get("vcodec")) or "h264"
        bucket = 60 if (info.get("fps") or 30) >= 50 else 30
        groups[(h, bucket, fam)] = info

    rows = [
        FormatRow(
            h, b, fam, f.get("vcodec") or ("avc1" if fam == "h264" else ""), f.get("ext") or "mp4",
            _size_of(f, duration),
            has_audio=audio_family(f.get("acodec")) is not None or str(f.get("acodec") or "") != "none",
        )
        for (h, b, fam), f in groups.items()
    ]
    rows.sort(key=lambda r: (-r.height, -r.fps, AUTO_ORDER.index(r.codec)))
    return rows


def best_audio(info: dict) -> Optional[AudioFacts]:
    duration = info.get("duration")
    streams = [
        f for f in info.get("formats") or []
        if codec_family(f.get("vcodec")) is None and audio_family(f.get("acodec"))
    ]
    if not streams:
        # On Instagram/X/Facebook, audio is often muxed inside the MP4 stream rather than a separate audio-only stream
        muxed = [
            f for f in info.get("formats") or []
            if audio_family(f.get("acodec"))
        ]
        if muxed:
            f = max(muxed, key=lambda s: s.get("abr") or s.get("tbr") or 0)
            abr = f.get("abr")
            return AudioFacts(None, round(abr) if abr else 128, audio_family(f.get("acodec")) or "AAC")
        return None
    f = max(streams, key=lambda s: s.get("abr") or s.get("tbr") or 0)
    abr = f.get("abr") or f.get("tbr")
    return AudioFacts(_size_of(f, duration), round(abr) if abr else None, audio_family(f.get("acodec")) or "?")


def _pretty_date(yyyymmdd) -> str:
    s = str(yyyymmdd or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else ""


def scan(
    url: str,
    playlist: bool = False,
    proxy: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
) -> ScanData:
    if spotify.is_spotify_url(url):
        sp = spotify.resolve_spotify(url, proxy=proxy)
        est_size = int(192 * 1000 / 8 * sp.duration) if sp.duration else None
        kind_badge = f"Spotify {sp.kind.upper()}"
        if len(sp.items) > 1:
            kind_badge += f" · {len(sp.items)} items"
        return ScanData(
            url=url,
            title=sp.title,
            channel=f"{sp.creator} ({kind_badge})",
            duration=sp.duration,
            upload_date="",
            rows=[],
            audio=AudioFacts(est_size, 192, "Spotify Audio"),
            spotify_data=sp,
            platform="spotify",
            media_kind=sp.kind,
            webpage_url=sp.url,
            has_chapters=False,
            has_subtitles=False,
        )

    detected = platforms.detect_platform(url)
    if detected.platform != "invalid" and not detected.supported:
        raise ValueError(detected.reason or f"Unsupported {detected.spec.name} URL.")

    target_url = detected.canonical_url if detected.canonical_url else url
    info = _extract(target_url, playlist, proxy, cookies_from_browser)
    _check_drm(info)

    rows = summarize_formats(info)
    audio = best_audio(info)

    # Detect image-only or text-only social media posts where no video or audio stream exists
    if not rows and audio is None and detected.platform in ("instagram", "twitter", "facebook"):
        raise RuntimeError(
            f"No downloadable video or audio stream found in this {detected.spec.name} {detected.kind} "
            "(it may be an image-only or text-only post)."
        )

    creator = platforms.extract_creator_handle(info, detected if detected.platform != "invalid" else None)
    has_chaps = bool(info.get("chapters"))
    has_subs = bool(info.get("subtitles") or info.get("automatic_captions"))

    return ScanData(
        url=url,
        title=info.get("title") or url,
        channel=creator or info.get("channel") or info.get("uploader") or "",
        duration=int(info["duration"]) if info.get("duration") else None,
        upload_date=_pretty_date(info.get("upload_date")),
        rows=rows,
        audio=audio,
        platform=detected.platform if detected.platform != "invalid" else "generic",
        media_kind=detected.kind if detected.platform != "invalid" else "video",
        webpage_url=str(info.get("webpage_url") or url),
        has_chapters=has_chaps,
        has_subtitles=has_subs,
    )


def count_playlist_entries(url, proxy=None, cookies_from_browser=None) -> int:
    if spotify.is_spotify_url(url):
        sp = spotify.resolve_spotify(url, proxy=proxy)
        return max(1, len(sp.items))
    if yt_dlp is None:
        return 1
    detected = platforms.detect_platform(url)
    target_url = detected.canonical_url if detected.canonical_url else url
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "logger": YdlLogger(),
    }
    if proxy:
        opts["proxy"] = proxy
    _apply_cookie_opts(opts, cookies_from_browser)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target_url, download=False) or {}
        entries = info.get("entries")
        if entries is None:
            return 1
        return max(1, len(list(entries)))


def pick_row(rows, height, codec, prefer_60fps, can_merge: bool = True):
    """Predict which row the format selector will land on. Returns (row, fell_back)."""
    pool = [r for r in rows if not height or r.height <= height]
    if not can_merge:
        merged_pool = [r for r in pool if r.has_audio]
        if merged_pool:
            pool = merged_pool
    want = 60 if prefer_60fps else 30

    def best(candidates):
        if not candidates:
            return None
        top = max(r.height for r in candidates)
        at_top = [r for r in candidates if r.height == top]
        return min(at_top, key=lambda r: (r.fps != want, AUTO_ORDER.index(r.codec)))

    hit = best([r for r in pool if codec is None or r.codec == codec])
    if hit:
        return hit, False
    return best(pool), codec is not None


def estimate_size(row: Optional[FormatRow], audio: Optional[AudioFacts]) -> Optional[int]:
    if row is None or row.size is None:
        return None
    if row.has_audio:
        return row.size
    return row.size + (audio.size if audio and audio.size else 0)


# ── time range, rate limit & download options ───────────────────────

def parse_time_seconds(token: str) -> Optional[float]:
    """Parse 'SS', 'MM:SS', or 'HH:MM:SS(.ms)' into seconds, or None if invalid."""
    t = token.strip()
    if not t:
        return None
    parts = t.split(":")
    if len(parts) > 3:
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    if any(v < 0 for v in vals):
        return None
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 2:
        if vals[1] >= 60:
            return None
        return vals[0] * 60 + vals[1]
    if vals[1] >= 60 or vals[2] >= 60:
        return None
    return vals[0] * 3600 + vals[1] * 60 + vals[2]


def parse_time_range(text: Optional[str]) -> Optional[tuple[float, float]]:
    """Parse '01:20-04:15' or '*90-180' into (start_seconds, end_seconds), or None."""
    raw = (text or "").strip().lstrip("*")
    if not raw or "-" not in raw:
        return None
    left, right = raw.split("-", 1)
    start = parse_time_seconds(left)
    end = parse_time_seconds(right)
    if start is None or end is None or end <= start:
        return None
    return (start, end)


@dataclass
class DownloadOptions:
    url: str
    outtmpl: str
    playlist: bool
    mode: str  # "video" | "audio"
    audio_format: Optional[str]
    bitrate: Optional[str]
    video_codec: Optional[str]
    target_resolution: Optional[int]
    prefer_60fps: bool
    proxy: Optional[str]
    ratelimit: Optional[int]
    archive_bundle: bool = False
    split_chapters: bool = False
    subs_mode: str = "off"  # "off" | "en" | "all" | "transcript"
    cookies_from_browser: Optional[str] = None
    time_range: Optional[str] = None


def build_video_format(target_resolution, codec, can_merge=True) -> str:
    """Format selector that degrades gracefully: codec -> any codec -> single file.

    Works across YouTube (adaptive DASH streams) and Instagram/X/Facebook (muxed MP4 or HLS).
    """
    h = f"[height<={target_resolution}]" if target_resolution else ""
    if not can_merge:  # no ffmpeg: only pre-merged single files are usable
        return "/".join(dict.fromkeys([f"b{h}", "b"]))
    pattern = CODEC_PATTERNS.get(codec) if codec else None
    c = f"[vcodec~='{pattern}']" if pattern else ""
    tiers = []
    if c and codec in MP4_CODECS:
        tiers.append(f"bv*{h}{c}+ba[ext=m4a]")
    tiers += [f"bv*{h}{c}+ba", f"bv*{h}+ba", f"b{h}", "b"]
    return "/".join(dict.fromkeys(tiers))


def parse_rate_limit(text) -> Optional[int]:
    """'1M' / '500k' / '120000' -> bytes per second, or None."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg])?b?(?:/s|ps)?", (text or "").strip(), re.I)
    if not m:
        return None
    val = float(m.group(1))
    if val <= 0:
        return None
    unit = {"": 1, "k": 1000, "m": 1000 ** 2, "g": 1000 ** 3}[(m.group(2) or "").lower()]
    return max(1, int(val * unit))


def build_ydl_opts(
    o: DownloadOptions,
    progress_hook,
    logger,
    on_file: Optional[Callable] = None,
    can_merge: Optional[bool] = None,
) -> dict:
    if can_merge is None:
        can_merge = is_ffmpeg_installed()

    opts: dict = {
        "outtmpl": o.outtmpl,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": [progress_hook],
        "noplaylist": not o.playlist,
        "noprogress": True,
        "logger": logger,
    }
    if on_file:
        opts["post_hooks"] = [on_file]  # called with each finished file's path
    if o.playlist:
        opts["ignoreerrors"] = "only_download"  # one dead item shouldn't kill the playlist/carousel
    if o.proxy:
        opts["proxy"] = o.proxy
    if o.ratelimit:
        opts["ratelimit"] = o.ratelimit
    _apply_cookie_opts(opts, o.cookies_from_browser)

    postprocessors: list[dict] = []

    if o.mode == "video":
        opts["format"] = build_video_format(o.target_resolution, o.video_codec, can_merge)
        opts["format_sort"] = ["res", "fps"] if o.prefer_60fps else ["res", "fps:30"]
        container = MERGE_CONTAINERS.get(o.video_codec)
        if container and can_merge:
            opts["merge_output_format"] = container
    else:
        opts["format"] = "bestaudio/best"
        if o.audio_format and o.audio_format != "best":
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": o.audio_format}
            if o.audio_format not in ("wav", "flac"):
                pp["preferredquality"] = o.bitrate or "192"
            postprocessors.append(pp)

    # Subtitle & Transcript Harvester
    if o.subs_mode in ("en", "all", "transcript") or o.archive_bundle:
        opts["writesubtitles"] = True
        if o.subs_mode == "all":
            opts["subtitleslangs"] = ["all"]
        else:
            opts["subtitleslangs"] = ["en.*", "en"]
            opts["writeautomaticsub"] = True
        opts["subtitlesformat"] = "vtt/srt/best"

    # Self-Contained Archival Bundle
    if o.archive_bundle and can_merge:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "FFmpegMetadata", "add_chapters": True, "add_metadata": True})
        if o.mode == "video":
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})
        if o.mode == "video" or o.audio_format in ("mp3", "m4a", "flac", None, "best"):
            postprocessors.append({"key": "EmbedThumbnail"})

    # Chapter Splitter
    if o.split_chapters and can_merge:
        postprocessors.append({"key": "FFmpegSplitChapters", "force_keyframes": False})

    # Time-Range Clipping
    parsed_range = parse_time_range(o.time_range)
    if parsed_range and can_merge:
        start_s, end_s = parsed_range
        opts["download_ranges"] = lambda info_dict, ydl: [{"start_time": start_s, "end_time": end_s}]
        opts["force_keyframes_at_cuts"] = True

    if postprocessors:
        opts["postprocessors"] = postprocessors
    return opts


def build_cli_command(o: DownloadOptions, can_merge: bool = True) -> str:
    """Build the human-readable equivalent `yt-dlp` or `spotdl` CLI command for the current form settings."""
    if spotify.is_spotify_url(o.url):
        parsed = spotify.parse_spotify_url(o.url)
        kind = parsed[0] if parsed else "track"
        fmt = o.audio_format if o.audio_format and o.audio_format != "best" else "mp3"
        if spotify.is_spotdl_installed() and kind in ("track", "album", "playlist"):
            return f"spotdl download {shlex.quote(o.url)} --format {fmt}"
        return f'yt-dlp -x --audio-format {fmt} --match-filter "duration>65" --embed-metadata "ytsearch5:<spotify:{kind}>"'
    args = ["yt-dlp"]
    if not o.playlist:
        args.append("--no-playlist")
    else:
        args.append("--yes-playlist")

    if o.mode == "video":
        fmt = build_video_format(o.target_resolution, o.video_codec, can_merge)
        args += ["-f", fmt]
        sort_val = "res,fps" if o.prefer_60fps else "res,fps:30"
        args += ["-S", sort_val]
        container = MERGE_CONTAINERS.get(o.video_codec)
        if container and can_merge:
            args += ["--merge-output-format", container]
    else:
        args += ["-f", "bestaudio/best"]
        if o.audio_format and o.audio_format != "best":
            args += ["-x", "--audio-format", o.audio_format]
            if o.audio_format not in ("wav", "flac") and o.bitrate:
                args += ["--audio-quality", f"{o.bitrate}K"]

    if o.archive_bundle and can_merge:
        args += ["--embed-metadata", "--embed-chapters", "--embed-thumbnail"]
        if o.mode == "video":
            args.append("--embed-subs")

    if o.subs_mode == "en":
        args += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en"]
    elif o.subs_mode == "all":
        args += ["--write-subs", "--sub-langs", "all"]
    elif o.subs_mode == "transcript":
        args += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*,en", "--sub-format", "vtt"]

    if o.split_chapters and can_merge:
        args.append("--split-chapters")

    parsed_range = parse_time_range(o.time_range)
    if parsed_range and can_merge:
        raw_range = (o.time_range or "").strip().lstrip("*")
        args += ["--download-sections", f"*{raw_range}"]

    if o.cookies_from_browser and o.cookies_from_browser != "none":
        args += ["--cookies-from-browser", o.cookies_from_browser]

    if o.ratelimit:
        args += ["-r", str(o.ratelimit)]
    if o.proxy:
        args += ["--proxy", o.proxy]
    if o.outtmpl and o.outtmpl != os.path.join(".", "%(title)s.%(ext)s"):
        args += ["-o", o.outtmpl]

    detected = platforms.detect_platform(o.url) if o.url else None
    url_display = (detected.canonical_url if detected and detected.canonical_url else o.url) if o.url else "<URL>"
    args.append(url_display)
    cmd_str = " ".join(
        shlex.quote(a) if (" " in a or "*" in a or "<" not in a and any(c in a for c in "&|;()")) else a
        for a in args
    )
    return platforms.redact_secrets(cmd_str)


# ── transcript cleaner (.vtt / .srt -> clean .txt) ──────────────────

_VTT_TAG_RE = re.compile(r"<[^>]+>")
_VTT_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->")


def vtt_to_clean_text(raw_vtt: str) -> str:
    """Strip WebVTT/SRT timestamps, headers, inline tags, and duplicate rolling lines into clean prose."""
    lines_out: list[str] = []
    for raw_line in raw_vtt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            continue
        if line.isdigit() or _VTT_TIME_RE.match(line):
            continue
        cleaned = _VTT_TAG_RE.sub("", line).replace("&nbsp;", " ").replace("&amp;", "&").strip()
        if not cleaned:
            continue
        if not lines_out or lines_out[-1] != cleaned:
            lines_out.append(cleaned)
    return "\n".join(lines_out)


def write_clean_transcripts(directory: str) -> list[str]:
    """Convert any .vtt / .srt files in `directory` into clean `.transcript.txt` files."""
    created: list[str] = []
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith((".vtt", ".srt")):
                txt_path = os.path.splitext(entry.path)[0] + ".transcript.txt"
                raw = Path(entry.path).read_text(encoding="utf-8", errors="replace")
                clean_txt = vtt_to_clean_text(raw)
                if clean_txt:
                    Path(txt_path).write_text(clean_txt + "\n", encoding="utf-8")
                    created.append(txt_path)
    except Exception:  # noqa: BLE001
        pass
    return created


# ── local Commons Catalog (~/.openband_catalog.json) ────────────────

@dataclass
class CatalogEntry:
    title: str
    channel: str
    url: str
    spec: str
    size: int
    path: str
    archived_at: str


def _default_catalog_path() -> Path:
    env_p = os.environ.get("OPENBAND_CATALOG_FILE")
    if env_p:
        return Path(env_p)
    return Path.home() / ".openband_catalog.json"


def load_catalog(catalog_path: Optional[Path] = None) -> list[CatalogEntry]:
    path = catalog_path or _default_catalog_path()
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [
                    CatalogEntry(
                        title=str(item.get("title", "")),
                        channel=str(item.get("channel", "")),
                        url=str(item.get("url", "")),
                        spec=str(item.get("spec", "")),
                        size=int(item.get("size", 0)),
                        path=str(item.get("path", "")),
                        archived_at=str(item.get("archived_at", "")),
                    )
                    for item in raw
                    if isinstance(item, dict)
                ]
    except Exception:  # noqa: BLE001
        pass
    return []


def append_catalog(entry: CatalogEntry, catalog_path: Optional[Path] = None) -> None:
    path = catalog_path or _default_catalog_path()
    items = load_catalog(path)
    items.insert(0, entry)  # newest first
    items = items[:250]     # cap history at 250 entries
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([asdict(x) for x in items], indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def clear_catalog(catalog_path: Optional[Path] = None) -> None:
    path = catalog_path or _default_catalog_path()
    try:
        if path.is_file():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


# ── Deeper Archival & Local Library Stewardship ──────────────────────

def export_catalog_m3u8(
    entries: Optional[list[CatalogEntry]] = None,
    dest_path: Optional[Path] = None,
) -> Path:
    """Export the local Commons Catalog to an Extended M3U (.m3u8) playlist for VLC, mpv, Jellyfin, or Navidrome."""
    items = entries if entries is not None else load_catalog()
    out = dest_path or (Path.home() / "openband_catalog.m3u8")
    lines = [
        "#EXTM3U",
        "#PLAYLIST:OpenBand Commons Catalog — User-Owned Media Archive",
    ]
    for e in items:
        artist_part = f"{e.channel} - " if e.channel else ""
        display = f"{artist_part}{e.title}".replace(",", " ")
        lines.append(f"#EXTINF:-1,{display}")
        if e.url:
            lines.append(f"#EXTVLCOPT:meta-url={e.url}")
        lines.append(e.path or e.url)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def export_catalog_markdown(
    entries: Optional[list[CatalogEntry]] = None,
    dest_path: Optional[Path] = None,
) -> Path:
    """Export the local Commons Catalog to a human-readable Markdown ledger (.md)."""
    items = entries if entries is not None else load_catalog()
    out = dest_path or (Path.home() / "openband_catalog.md")
    total_bytes = sum(e.size for e in items if e.size)
    size_mb = f"{total_bytes / 1e6:.1f} MB" if total_bytes < 1e9 else f"{total_bytes / 1e9:.2f} GB"
    lines = [
        "# ((●)) OPENBAND · LOCAL COMMONS CATALOG",
        "",
        "> *Your media. Your terms. Less lock-in. More freedom.*",
        "",
        f"- **Archived Items:** {len(items)}",
        f"- **Total Local Footprint:** {size_mb}",
        "",
        "| Archived | Title | Creator | Spec | Size | Local Path | Source URL |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for e in items:
        sz = f"{e.size / 1e6:.1f} MB" if e.size >= 1e6 else f"{max(e.size, 0) / 1e3:.0f} KB"
        safe_title = e.title.replace("|", "·")
        safe_chan = e.channel.replace("|", "·")
        safe_spec = e.spec.replace("|", "·")
        lines.append(
            f"| {e.archived_at} | **{safe_title}** | {safe_chan} | `{safe_spec}` | {sz} | `{e.path}` | {e.url} |"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def export_catalog_csv(
    entries: Optional[list[CatalogEntry]] = None,
    dest_path: Optional[Path] = None,
) -> Path:
    """Export the local Commons Catalog to a standard UTF-8 CSV spreadsheet."""
    import csv
    items = entries if entries is not None else load_catalog()
    out = dest_path or (Path.home() / "openband_catalog.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(["archived_at", "title", "creator", "spec", "size_bytes", "path", "source_url"])
        for e in items:
            writer.writerow([e.archived_at, e.title, e.channel, e.spec, e.size, e.path, e.url])
    return out


def write_provenance_nfo(
    media_path: str,
    *,
    title: str,
    creator: str,
    source_url: str,
    platform: str = "generic",
    spec: str = "",
    upload_date: str = "",
    description: str = "",
    archived_at: Optional[str] = None,
) -> Optional[Path]:
    """Write a Kodi/Jellyfin/Plex-compatible XML `.nfo` provenance sidecar alongside an archived media file."""
    import xml.sax.saxutils as saxutils
    if not media_path:
        return None
    base, _ = os.path.splitext(media_path)
    nfo_path = Path(f"{base}.nfo")
    ts = archived_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    year = upload_date[:4] if upload_date and len(upload_date) >= 4 else ts[:4]
    esc = saxutils.escape
    plot_lines = [p for p in (description.strip(), f"Source URL: {source_url}", f"Archived via OpenBand ({spec}) on {ts}") if p]
    plot_text = "\n\n".join(plot_lines)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
        "<musicvideo>\n"
        f"  <title>{esc(title)}</title>\n"
        f"  <artist>{esc(creator)}</artist>\n"
        f"  <studio>{esc(platform.upper())}</studio>\n"
        f"  <premiered>{esc(upload_date or ts[:10])}</premiered>\n"
        f"  <year>{esc(year)}</year>\n"
        f"  <plot>{esc(plot_text)}</plot>\n"
        f'  <uniqueid type="url" default="true">{esc(source_url)}</uniqueid>\n'
        "</musicvideo>\n"
    )
    try:
        nfo_path.parent.mkdir(parents=True, exist_ok=True)
        nfo_path.write_text(xml_content, encoding="utf-8")
        return nfo_path
    except Exception:  # noqa: BLE001
        return None


def find_transcript_for_media(media_path: str) -> Optional[Path]:
    """Locate a harvested `.transcript.txt` (or `.vtt`/`.srt`) file corresponding to `media_path`."""
    if not media_path:
        return None
    p = Path(media_path)
    stem = p.stem
    parent = p.parent
    if not parent.is_dir():
        return None
    # 1. Exact stem match or language-suffixed match (e.g. video.en.transcript.txt)
    candidates = sorted(parent.glob(f"{stem}*.transcript.txt"))
    if candidates:
        return candidates[0]
    # 2. If a raw .vtt/.srt exists next to it, convert on the fly and return
    vtts = sorted(list(parent.glob(f"{stem}*.vtt")) + list(parent.glob(f"{stem}*.srt")))
    if vtts:
        created = write_clean_transcripts(str(parent))
        if created:
            for c in created:
                if Path(c).name.startswith(stem):
                    return Path(c)
            return Path(created[0])
    return None


# ── Batch URL Parsing & Import ──────────────────────────────────────

_URL_TOKEN_RE = re.compile(
    r"""(?:https?://[^\s<>"'`]+|spotify:(?:track|playlist|album|episode|show):[A-Za-z0-9]+)""",
    re.I,
)


def parse_batch_urls(raw_text: str) -> list[str]:
    """Extract a deduplicated, ordered list of media URLs / Spotify URIs from multi-line text,
    markdown lists, or space/comma/semicolon-separated input, ignoring `#` comment lines.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Strip inline comment after whitespace + #
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        matches = _URL_TOKEN_RE.findall(line)
        if matches:
            for m in matches:
                cleaned_u = m.rstrip(".,;)]>")
                if cleaned_u and cleaned_u not in seen:
                    seen.add(cleaned_u)
                    urls.append(cleaned_u)
        else:
            # Check if the line itself is a single token
            token = line.strip(".,;)]> ")
            if token and ("://" in token or token.lower().startswith("spotify:")) and token not in seen:
                seen.add(token)
                urls.append(token)
    return urls


def load_batch_file(filepath: str | Path) -> list[str]:
    """Read a batch text/markdown file of URLs (ignoring comments and blank lines)."""
    p = Path(os.path.expanduser(str(filepath).strip()))
    if not p.is_file():
        raise FileNotFoundError(f"Batch file not found: {p}")
    content = p.read_text(encoding="utf-8", errors="replace")
    return parse_batch_urls(content)


# ── presets & profiles (~/.openband.toml) ───────────────────────────

@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    mode: str          # "video" | "audio"
    codec: str         # "none" | "h264" | "h265" | "vp9" | "av1"
    res: str | int     # "auto" | 1080 | 720 | 2160
    fps60: bool
    aformat: str       # "best" | "mp3" | "m4a" | "wav" | "flac"
    bitrate: str       # "default" | "128" | "192" | "256" | "320"
    archive_bundle: bool
    subs_mode: str     # "off" | "en" | "all" | "transcript"


PRESETS: dict[str, Preset] = {
    "1": Preset("1", "TV-Safe MP4 (1080p H.264)", "video", "h264", 1080, False, "best", "default", False, "off"),
    "2": Preset("2", "Full Archive Bundle (Max + Meta/Subs)", "video", "none", "auto", True, "best", "default", True, "en"),
    "3": Preset("3", "Universal MP3 (320 kbps + Meta)", "audio", "none", "auto", False, "mp3", "320", True, "off"),
    "4": Preset("4", "Lossless FLAC Studio", "audio", "none", "auto", False, "flac", "default", True, "off"),
}


def load_presets(config_path: Optional[Path] = None) -> dict[str, Preset]:
    """Load built-in presets, optionally overridden by `~/.openband.toml` if present."""
    presets = dict(PRESETS)
    path = config_path or (Path.home() / ".openband.toml")
    if not path.is_file():
        return presets
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for k, v in (data.get("presets") or {}).items():
            if isinstance(v, dict):
                presets[str(k)] = Preset(
                    key=str(k),
                    name=str(v.get("name", f"Preset {k}")),
                    mode=str(v.get("mode", "video")),
                    codec=str(v.get("codec", "h264")),
                    res=v.get("res", "auto"),
                    fps60=bool(v.get("fps60", False)),
                    aformat=str(v.get("aformat", "best")),
                    bitrate=str(v.get("bitrate", "default")),
                    archive_bundle=bool(v.get("archive_bundle", False)),
                    subs_mode=str(v.get("subs_mode", "off")),
                )
    except Exception:  # noqa: BLE001
        pass
    return presets


# ── clipboard & file helpers ────────────────────────────────────────

def read_clipboard() -> str:
    """Read plain text from the system clipboard across macOS, Windows, and Linux."""
    system = platform.system()
    cmds = []
    if system == "Darwin":
        cmds = [["pbpaste"]]
    elif system == "Windows":
        cmds = [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]
    else:
        cmds = [
            ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ]
    for cmd in cmds:
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:  # noqa: BLE001
                continue
    return ""


def copy_to_clipboard(text: str) -> bool:
    """Copy plain text to the system clipboard across macOS, Windows, and Linux."""
    system = platform.system()
    cmds = []
    if system == "Darwin":
        cmds = [["pbcopy"]]
    elif system == "Windows":
        cmds = [["clip"]]
    else:
        cmds = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    for cmd in cmds:
        if shutil.which(cmd[0]):
            try:
                res = subprocess.run(cmd, input=text, text=True, timeout=2, check=False)
                if res.returncode == 0:
                    return True
            except Exception:  # noqa: BLE001
                continue
    return False


# ── progress + "what did I actually get" ────────────────────────────

@dataclass(frozen=True)
class Got:
    codec: Optional[str]   # video codec family, None for audio-only
    acodec: Optional[str]  # "AAC", "Opus", ...
    height: Optional[int]
    fps: Optional[int]
    ext: str


def summarize_got(info: dict) -> Got:
    req = info.get("requested_formats")
    if req and isinstance(req, (list, tuple)):
        v_stream = next((f for f in req if isinstance(f, dict) and codec_family(f.get("vcodec"))), {})
        a_stream = next((f for f in req if isinstance(f, dict) and audio_family(f.get("acodec"))), {})
        vcodec = v_stream.get("vcodec") or info.get("vcodec")
        acodec = a_stream.get("acodec") or info.get("acodec")
        height = v_stream.get("height") or info.get("height")
        fps = v_stream.get("fps") or info.get("fps")
    else:
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        height = info.get("height")
        fps = info.get("fps")

    v_fam = codec_family(vcodec)
    ext = MERGE_CONTAINERS.get(v_fam) if (req and v_fam in MERGE_CONTAINERS) else (info.get("ext") or "")
    return Got(
        v_fam,
        audio_family(acodec),
        height,
        round(fps) if fps else None,
        ext,
    )


def make_progress_hook(playlist_total, push, is_cancelled, on_item=None):
    """yt-dlp progress hook -> push(overall_fraction, label)."""
    seen: dict = {}
    last = [-1.0]

    def hook(d):
        if is_cancelled():
            raise DownloadCancelled("cancelled")
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return
        info = d.get("info_dict") or {}
        index = info.get("playlist_index")
        item = index or 1
        req = info.get("requested_formats")
        streams = len(req) if isinstance(req, (list, tuple)) and len(req) > 0 else 1
        stream_id = d.get("filename") or info.get("format_id") or "0"
        key = (item, stream_id)
        if key not in seen:
            seen[key] = min(sum(1 for k in seen if k[0] == item), streams - 1)
        if status == "finished" and on_item:
            on_item(item, info)

        if status == "finished":
            frac = 1.0
        else:
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                frac = (d.get("downloaded_bytes") or 0) / total
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                frac = 0.0
        item_frac = min((seen[key] + frac) / streams, 1.0)

        if playlist_total:
            overall = min(((item - 1) + item_frac) / playlist_total, 1.0)
            label = f"{item}/{playlist_total}"
        else:
            overall = item_frac
            label = f"item {item}" if index else ""

        if status == "downloading":
            speed = d.get("speed")
            if speed:
                label = f"{label}  {speed / 1_048_576:.1f} MiB/s".strip()
        if status == "finished" or abs(overall - last[0]) >= 0.004:
            last[0] = overall
            push(overall, label)

    return hook


# ── friendly errors (YouTube, Spotify, Instagram, X/Twitter, Facebook) ──

@dataclass(frozen=True)
class Friendly:
    headline: str
    hint: str


_ERRORS = [
    (r"DRM[- ]protected|has_drm|Widevine|PlayReady|FairPlay",
     "This media is DRM-protected.",
     "OpenBand respects technical access controls and does not bypass DRM."),
    (r"No video could be found in this tweet|There is no video in this post|No downloadable video or audio stream found|image-only or text-only",
     "No video or audio stream in this post.",
     "This post appears to contain only static images or text. Paste a Reel, video post, or audio Space link."),
    (r"Instagram.*login_required|login_required.*Instagram|Instagram.*rate-limit|Requested content is not available|InstagramStory",
     "Instagram requires authentication for this post or Story.",
     "Open F7 → COOKIES and select your signed-in browser (Firefox/Chrome/Brave) to access authorized content."),
    (r"NSFW tweet|age-restricted tweet|Twitter.*login|guest token|This Tweet is from a suspended account|status.*not found.*twitter",
     "X (Twitter) restricted access to this post.",
     "If the post is age-restricted or protected and you have access, select your signed-in browser under F7 → COOKIES."),
    (r"This video is only available to|login required.*facebook|facebook.*login|Cannot parse data.*facebook|fb\.watch.*expired",
     "Facebook requires login or the video link has expired.",
     "If you are entitled to view this video, select your signed-in browser under F7 → COOKIES, or check the link."),
    (r"HTTP Error 403|Forbidden",
     "The platform refused the download (403).",
     "Usually an expired session, outdated yt-dlp, or missing JS runtime. Press F9 to update, or set F7 → COOKIES."),
    (r"HTTP Error 404|410 Gone|status code 404",
     "Media not found or link has expired (404).",
     "Verify the URL in your browser — the post may have been deleted or the share link expired."),
    (r"HTTP Error 429|Too Many Requests|rate[- ]limit",
     "Too many requests / rate-limited (429).",
     "Wait a few minutes, set a speed limit (F7 → LIMIT), or authenticate via F7 → COOKIES."),
    (r"not a bot|confirm you.re not|checkpoint_required",
     "The platform is asking for human/account verification.",
     "Open F7 → COOKIES and select your signed-in browser (Firefox/Chrome/Brave), or update yt-dlp (F9)."),
    (r"age[- ]restrict|confirm your age|inappropriate for some users",
     "Age-restricted media.",
     "Open F7 → COOKIES and select your signed-in browser to unlock it."),
    (r"Private video|Private account|is private",
     "This media is private.",
     "If you have authorized access, select your signed-in browser under F7 → COOKIES."),
    (r"not available in your country|blocked it in your country|geo.?restrict",
     "Not available in your region.",
     "A proxy in another country (F7 → PROXY) may help."),
    (r"Video unavailable|has been removed|no longer available|does not exist",
     "Media unavailable.",
     "It may have been removed, expired, or made private."),
    (r"Requested format is not available",
     "That format isn't available for this media item.",
     "Set codec / resolution to AUTO, or scan (F2) and pick from the real list (F3)."),
    (r"ffmpeg|ffprobe",
     "ffmpeg is missing or failed.",
     "Press F1 for install steps."),
    (r"Unsupported URL|Unsupported .* URL|Unsupported .* page|profile links .* cannot be downloaded|aren't single media items",
     "That link isn't supported.",
     "Paste a direct video, Reel, post, playlist, or Spotify link."),
    (r"is not a valid URL|doesn't look like a valid URL|Malformed URL|Missing domain name",
     "That doesn't look like a valid link.",
     "Paste a full URL starting with https://"),
    (r"getaddrinfo|Name or service not known|Temporary failure in name resolution|timed out|"
     r"Connection (?:refused|reset|aborted)|Network is unreachable|Unable to download (?:webpage|API|JSON)",
     "Can't reach the platform.",
     "Check your internet connection or proxy (F7 → PROXY), then try again."),
]


def friendly_error(text) -> Friendly:
    message = clean(text)
    for pattern, headline, hint in _ERRORS:
        if re.search(pattern, message, re.I):
            return Friendly(headline, hint)
    first = re.sub(r"^ERROR:\s*", "", message.splitlines()[0] if message else "unknown error")
    return Friendly(first[:160], "")


# ── updates ─────────────────────────────────────────────────────────

def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def is_newer(latest: str, current: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def latest_ytdlp_version(timeout: float = 6.0) -> Optional[str]:
    """Latest release on PyPI, or None if offline. The only network call besides downloads."""
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=timeout) as r:
            return json.load(r)["info"]["version"]
    except Exception:  # noqa: BLE001
        return None


def update_ytdlp(sink: Callable[[str], None]) -> int:
    cmd = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "--disable-pip-version-check"]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.strip():
            sink(clean(line))
    return proc.wait()


# ── misc ────────────────────────────────────────────────────────────

def open_folder(path: str) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: S606
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_file(path: str) -> None:
    """Open a media file in the user's default system player."""
    open_folder(path)
