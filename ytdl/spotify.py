"""spotify — Spotify song, album, playlist & podcast resolver and multi-pass downloader for OpenBand.

Resolves Spotify URLs (`open.spotify.com` or `spotify:...` URIs) via public embed/oEmbed
endpoints without requiring a paid Spotify Developer API key, and bridges downloads via:
1. `spotdl` CLI (if installed on PATH) for song/album/playlist tracks, or
2. OpenBand's duration-verified `yt-dlp` multi-candidate matcher (`ytsearch5:...`) with
   a separate flat-search extractor and automatic multi-pass retry for failed items.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
except ModuleNotFoundError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]

    class DownloadCancelled(Exception):  # type: ignore[no-redef]
        pass

__all__ = [
    "SPOTIFY_URL_RE",
    "MIN_TRACK_SECONDS",
    "SpotifyItem",
    "SpotifyResolved",
    "SpotifyDownloadReport",
    "is_spotify_url",
    "is_spotdl_installed",
    "parse_spotify_url",
    "score_candidate",
    "pick_best_candidate",
    "rank_candidates",
    "resolve_spotify",
    "download_spotify",
]

# Matches https://open.spotify.com/(intl-xx/)?(track|playlist|album|episode|show)/<id> or spotify:<kind>:<id>
SPOTIFY_URL_RE = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?(track|playlist|album|episode|show)/([a-zA-Z0-9]+)"
    r"|spotify:(track|playlist|album|episode|show):([a-zA-Z0-9]+))",
    re.I,
)

# Minimum acceptable duration for a normal song when Spotify doesn't specify a shorter duration
MIN_TRACK_SECONDS = 65

# Keywords in candidate titles that strongly indicate a 20-30s snippet or short rather than a full track
SNIPPET_KEYWORDS_RE = re.compile(
    r"\b(shorts|#shorts|snippet|teaser|preview|trailer|ringtone|status|tiktok|reel|clip|30\s*sec|20\s*sec)\b",
    re.I,
)

# Keywords in candidate titles/descriptions that indicate an official full-length audio track
OFFICIAL_AUDIO_RE = re.compile(
    r"\b(official\s+audio|provided\s+to\s+youtube\s+by|auto-generated\s+by\s+youtube|lyric\s+video|topic)\b",
    re.I,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SpotifyItem:
    title: str
    artist: str          # Artist for songs, or Show/Publisher for podcasts
    duration: Optional[int] = None  # Full duration in seconds (None if unknown, never 29-30s preview)
    kind: str = "track"  # "track" | "episode"
    index: int = 1
    thumbnail: Optional[str] = None
    audio_preview_url: Optional[str] = None

    @property
    def search_query(self) -> str:
        if self.kind == "episode":
            return f"{self.artist} {self.title} full episode podcast".strip()
        if self.artist:
            return f"{self.artist} - {self.title} official audio".strip()
        return f"{self.title} official audio".strip()

    @property
    def fallback_query(self) -> str:
        if self.kind == "episode":
            return f"{self.artist} {self.title} podcast".strip()
        if self.artist:
            return f"{self.artist} - {self.title}".strip()
        return self.title.strip()

    @property
    def lyric_query(self) -> str:
        if self.kind == "episode":
            return f"{self.title} {self.artist}".strip()
        if self.artist:
            return f"{self.artist} {self.title} lyrics".strip()
        return f"{self.title} lyrics".strip()


@dataclass
class SpotifyResolved:
    url: str
    kind: str            # "track" | "playlist" | "album" | "episode" | "show"
    item_id: str
    title: str
    creator: str         # Artist, playlist owner, or podcast publisher
    duration: Optional[int]
    items: list[SpotifyItem] = field(default_factory=list)
    thumbnail: Optional[str] = None


@dataclass
class SpotifyDownloadReport:
    files: list[str] = field(default_factory=list)
    failed_items: list[SpotifyItem] = field(default_factory=list)
    recovered_on_retry: int = 0


def is_spotify_url(url: str) -> bool:
    return parse_spotify_url(url) is not None


def is_spotdl_installed() -> bool:
    return shutil.which("spotdl") is not None


def parse_spotify_url(url: str) -> Optional[tuple[str, str]]:
    """Return `(kind, item_id)` for a Spotify link or URI, or `None` if not a Spotify link."""
    m = SPOTIFY_URL_RE.search((url or "").strip())
    if not m:
        return None
    kind = (m.group(1) or m.group(3)).lower()
    item_id = m.group(2) or m.group(4)
    return kind, item_id


def _sanitize_spotify_duration(dur_ms: Optional[int | float], kind: str = "track") -> Optional[int]:
    """Convert Spotify embed millisecond duration to seconds, ignoring 29-30s preview lengths."""
    if not isinstance(dur_ms, (int, float)) or dur_ms <= 0:
        return None
    sec = int(round(dur_ms / 1000.0))
    if sec <= 32:
        return None
    return sec


# ── Duration-Aware Candidate Scoring & Full-Track Selection ─────────

def score_candidate(entry: dict, item: SpotifyItem) -> float:
    """Score a YouTube search result dictionary for how well it matches the full-length `SpotifyItem`.

    Returns a negative score (`-1000.0`) for 20-30s snippets, YouTube Shorts, or livestreams.
    """
    if not isinstance(entry, dict):
        return -1000.0

    if entry.get("is_live") or entry.get("live_status") in ("is_live", "is_upcoming"):
        return -1000.0

    cand_dur = entry.get("duration")
    target_dur = item.duration
    cand_title = str(entry.get("title") or "")
    cand_channel = str(entry.get("channel") or entry.get("uploader") or "")
    cand_url = str(entry.get("webpage_url") or entry.get("url") or "")
    if not cand_url and entry.get("id"):
        cand_url = f"https://www.youtube.com/watch?v={entry['id']}"

    # 1. Hard rejection of YouTube Shorts URLs and 20-45s snippets
    if "/shorts/" in cand_url.lower():
        return -1000.0

    min_allowed = MIN_TRACK_SECONDS if item.kind == "track" else 90
    if target_dur and target_dur > 45:
        min_allowed = max(45, int(target_dur * 0.6))

    if isinstance(cand_dur, (int, float)):
        if cand_dur < min_allowed:
            return -1000.0
        if item.kind == "track" and not target_dur and cand_dur > 900:
            return -500.0
    else:
        return -200.0

    score = 100.0

    # 2. Duration closeness scoring (when Spotify gave us the real track duration)
    if target_dur and isinstance(cand_dur, (int, float)):
        diff = abs(float(cand_dur) - float(target_dur))
        if diff <= 3:
            score += 60.0
        elif diff <= 8:
            score += 45.0
        elif diff <= 15:
            score += 25.0
        elif diff <= 30:
            score += 5.0
        else:
            score -= min(120.0, diff * 1.2)
    elif isinstance(cand_dur, (int, float)):
        if item.kind == "track" and 120 <= cand_dur <= 420:
            score += 30.0
        elif item.kind == "episode" and cand_dur >= 300:
            score += 30.0

    # 3. Title & Channel quality signals
    want_snippet = bool(SNIPPET_KEYWORDS_RE.search(item.title))
    if not want_snippet and SNIPPET_KEYWORDS_RE.search(cand_title):
        score -= 150.0

    combined_meta = f"{cand_title} {cand_channel} {entry.get('description') or ''}"
    if OFFICIAL_AUDIO_RE.search(combined_meta):
        score += 25.0
    if cand_channel.endswith(" - Topic"):
        score += 35.0

    if item.title.lower() in cand_title.lower():
        score += 20.0
    if item.artist:
        primary_artist = item.artist.split(",")[0].strip().lower()
        if primary_artist and (primary_artist in cand_title.lower() or primary_artist in cand_channel.lower()):
            score += 20.0

    return score


def rank_candidates(entries: list[dict], item: SpotifyItem) -> list[dict]:
    """Return all valid full-length candidates ordered from best score to worst."""
    valid = [e for e in (entries or []) if isinstance(e, dict)]
    if not valid:
        return []
    scored = [(score_candidate(e, item), idx, e) for idx, e in enumerate(valid)]
    scored.sort(key=lambda tup: (-tup[0], tup[1]))
    return [e for score, _, e in scored if score > -500.0]


def pick_best_candidate(entries: list[dict], item: SpotifyItem) -> Optional[dict]:
    """Select the highest-scoring full-length candidate from a list of `ytsearch` results."""
    ranked = rank_candidates(entries, item)
    return ranked[0] if ranked else None


# ── Spotify Embed / oEmbed Resolution ───────────────────────────────

def _fetch_text(url: str, proxy: Optional[str] = None, timeout: float = 10.0) -> str:
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_next_data(page_html: str) -> Optional[dict]:
    """Extract JSON payload from Spotify Embed's `<script id="__NEXT_DATA__">` tag."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_html,
        re.S | re.I,
    )
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1).strip()))
    except Exception:  # noqa: BLE001
        return None


def _parse_embed_entity(data: dict, kind: str, item_id: str, url: str) -> Optional[SpotifyResolved]:
    """Parse Spotify embed `__NEXT_DATA__` JSON structure into `SpotifyResolved`."""
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        return None
    if not isinstance(entity, dict):
        return None

    title = str(entity.get("name") or entity.get("title") or f"Spotify {kind.title()}")
    subtitle = str(entity.get("subtitle") or "")
    if not subtitle and isinstance(entity.get("artists"), list):
        subtitle = ", ".join(str(a.get("name", "")) for a in entity["artists"] if isinstance(a, dict) and a.get("name"))
    if not subtitle and isinstance(entity.get("show"), dict):
        subtitle = str(entity["show"].get("name") or entity["show"].get("publisher") or "")

    dur_ms = entity.get("duration") or entity.get("duration_ms")
    duration = _sanitize_spotify_duration(dur_ms, kind)

    thumb = None
    cover = entity.get("coverArt") or entity.get("visualIdentity") or {}
    if isinstance(cover, dict):
        sources = cover.get("sources") or (cover.get("image") if isinstance(cover.get("image"), list) else [])
        if isinstance(sources, list) and sources:
            first_src = sources[0]
            if isinstance(first_src, dict):
                thumb = first_src.get("url")

    items: list[SpotifyItem] = []
    track_list = entity.get("trackList") or entity.get("episodes") or []
    if isinstance(track_list, list) and track_list:
        item_kind = "episode" if kind in ("show", "episode") else "track"
        for idx, t in enumerate(track_list, start=1):
            if not isinstance(t, dict):
                continue
            t_title = str(t.get("title") or t.get("name") or f"Track {idx}")
            t_artist = str(t.get("subtitle") or subtitle or "")
            t_dur_ms = t.get("duration") or t.get("duration_ms")
            t_dur = _sanitize_spotify_duration(t_dur_ms, item_kind)
            preview = None
            if item_kind == "episode":
                ap = t.get("audioPreview")
                if isinstance(ap, dict):
                    preview = ap.get("url")
            items.append(
                SpotifyItem(
                    title=t_title,
                    artist=t_artist,
                    duration=t_dur,
                    kind=item_kind,
                    index=idx,
                    thumbnail=thumb,
                    audio_preview_url=preview,
                )
            )
    else:
        item_kind = "episode" if kind in ("episode", "show") else "track"
        preview = None
        if item_kind == "episode":
            ap = entity.get("audioPreview")
            if isinstance(ap, dict):
                preview = ap.get("url")
        items.append(
            SpotifyItem(
                title=title,
                artist=subtitle,
                duration=duration,
                kind=item_kind,
                index=1,
                thumbnail=thumb,
                audio_preview_url=preview,
            )
        )

    total_dur = duration or sum(i.duration or 0 for i in items) or None
    return SpotifyResolved(
        url=url,
        kind=kind,
        item_id=item_id,
        title=title,
        creator=subtitle or "Spotify",
        duration=total_dur,
        items=items,
        thumbnail=thumb,
    )


def _parse_oembed_fallback(kind: str, item_id: str, url: str, proxy: Optional[str] = None) -> SpotifyResolved:
    """Fallback to Spotify's public oEmbed endpoint if embed HTML parsing fails."""
    canonical = f"https://open.spotify.com/{kind}/{item_id}"
    oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(canonical, safe='')}"
    raw = _fetch_text(oembed_url, proxy=proxy)
    data = json.loads(raw)
    raw_title = str(data.get("title") or f"Spotify {kind.title()} {item_id}")
    thumb = data.get("thumbnail_url")
    if " - " in raw_title:
        title, creator = raw_title.split(" - ", 1)
    elif " · " in raw_title:
        title, creator = raw_title.split(" · ", 1)
    else:
        title, creator = raw_title, str(data.get("provider_name") or "Spotify")
    item_kind = "episode" if kind in ("episode", "show") else "track"
    item = SpotifyItem(title=title.strip(), artist=creator.strip(), kind=item_kind, index=1, thumbnail=thumb)
    return SpotifyResolved(
        url=url,
        kind=kind,
        item_id=item_id,
        title=title.strip(),
        creator=creator.strip(),
        duration=None,
        items=[item],
        thumbnail=thumb,
    )


def resolve_spotify(url: str, proxy: Optional[str] = None) -> SpotifyResolved:
    """Resolve a Spotify track, album, playlist, podcast episode, or podcast show URL."""
    parsed = parse_spotify_url(url)
    if not parsed:
        raise ValueError("Not a valid Spotify URL or URI.")
    kind, item_id = parsed
    embed_url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    try:
        page_html = _fetch_text(embed_url, proxy=proxy)
        next_data = _extract_next_data(page_html)
        if next_data:
            resolved = _parse_embed_entity(next_data, kind, item_id, url)
            if resolved:
                return resolved
    except Exception:  # noqa: BLE001
        pass

    return _parse_oembed_fallback(kind, item_id, url, proxy=proxy)


def _write_id3_sidecar_tags(filepath: str, item: SpotifyItem, album_title: str) -> None:
    """Embed Title, Artist, Track Number, and Album/Show into the audio file via ffmpeg if needed."""
    if not os.path.exists(filepath) or not shutil.which("ffmpeg"):
        return
    base, ext = os.path.splitext(filepath)
    tmp_path = f"{base}.tagged{ext}"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", filepath,
        "-c", "copy",
        "-metadata", f"title={item.title}",
        "-metadata", f"artist={item.artist}",
        "-metadata", f"album={album_title}",
        "-metadata", f"track={item.index}",
        tmp_path,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if res.returncode == 0 and os.path.exists(tmp_path):
            os.replace(tmp_path, filepath)
        elif os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:  # noqa: BLE001
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _candidate_url(entry: dict) -> Optional[str]:
    url = entry.get("webpage_url") or entry.get("url")
    if url:
        return str(url)
    vid = entry.get("id")
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def _find_candidate_urls(
    item: SpotifyItem,
    *,
    proxy: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    pass_num: int = 1,
    log_cb: Optional[Callable[[str, str], None]] = None,
) -> list[str]:
    """Use a fast flat-search YoutubeDL instance (without match_filter!) to rank full-track URLs.

    Why separate from the download YoutubeDL instance:
    In yt-dlp, if `match_filter` is set during `ytsearch5:`, a single short result in the
    top 5 causes yt-dlp to log an error or abort the search batch even when the other 4
    results are full-length songs. Using `extract_flat="in_playlist"` avoids per-candidate
    stream extraction and returns all 5 candidates' durations cleanly in ~0.3s.
    """
    search_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "noplaylist": True,
        "ignoreerrors": True,
    }
    if proxy:
        search_opts["proxy"] = proxy
    if cookies_from_browser and cookies_from_browser != "none":
        search_opts["cookiesfrombrowser"] = (cookies_from_browser,)

    queries = (
        [f"ytsearch5:{item.search_query}", f"ytsearch5:{item.fallback_query}"]
        if pass_num == 1
        else [f"ytsearch8:{item.fallback_query}", f"ytsearch8:{item.lyric_query}", f"ytsearch5:{item.search_query}"]
    )

    urls: list[str] = []
    seen_urls: set[str] = set()

    with yt_dlp.YoutubeDL(search_opts) as search_ydl:
        for q in queries:
            try:
                info = search_ydl.extract_info(q, download=False)
                entries = list((info or {}).get("entries") or [])
                ranked = rank_candidates(entries, item)
                for cand in ranked:
                    u = _candidate_url(cand)
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        urls.append(u)
                        if len(urls) == 1 and log_cb:
                            c_dur = cand.get("duration")
                            if isinstance(c_dur, (int, float)):
                                m, s = divmod(int(c_dur), 60)
                                log_cb(f"  matched full stream: {cand.get('title', item.title)} ({m}:{s:02d})", "note")
                if urls:
                    break
            except DownloadCancelled:
                raise
            except Exception:  # noqa: BLE001
                continue

    return urls


def _download_single_spotify_item(
    item: SpotifyItem,
    *,
    idx: int,
    total: int,
    album_title: str,
    out_dir: str,
    fmt: str,
    audio_format: str,
    kbps: str,
    playlist_numbering: bool,
    proxy: Optional[str],
    ratelimit: Optional[int],
    cookies_from_browser: Optional[str],
    can_merge: bool,
    pass_num: int,
    progress_cb: Optional[Callable[[float, str], None]],
    log_cb: Optional[Callable[[str, str], None]],
    is_cancelled: Optional[Callable[[], bool]],
) -> list[str]:
    """Attempt to resolve and download a single `SpotifyItem` across its top ranked candidates."""
    if is_cancelled and is_cancelled():
        raise DownloadCancelled("cancelled")

    prefix = f"{item.index:02d} - " if (total > 1 and playlist_numbering) else ""
    safe_artist = re.sub(r'[\\/*?:"<>|]', "", item.artist).strip()
    safe_title = re.sub(r'[\\/*?:"<>|]', "", item.title).strip()
    stem = f"{prefix}{safe_artist} - {safe_title}" if safe_artist else f"{prefix}{safe_title}"
    outtmpl = os.path.join(out_dir, f"{stem}.%(ext)s")

    if log_cb:
        kind_tag = "podcast episode" if item.kind == "episode" else "track"
        dur_hint = ""
        if item.duration:
            dm, ds = divmod(int(item.duration), 60)
            dur_hint = f" [target {dm}:{ds:02d}]"
        pass_tag = f" (retry pass {pass_num})" if pass_num > 1 else ""
        log_cb(f"[{idx}/{total}]{pass_tag} resolving full {kind_tag}: {item.fallback_query}{dur_hint}", "note")

    candidate_urls = _find_candidate_urls(
        item,
        proxy=proxy,
        cookies_from_browser=cookies_from_browser,
        pass_num=pass_num,
        log_cb=log_cb,
    )
    if not candidate_urls:
        candidate_urls = [f"ytsearch1:{item.search_query}"]

    item_files: list[str] = []

    def _item_hook(d, item_idx=idx):
        if is_cancelled and is_cancelled():
            raise DownloadCancelled("cancelled")
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return
        if status == "finished":
            frac = 1.0
        else:
            tb = d.get("total_bytes") or d.get("total_bytes_estimate")
            frac = (d.get("downloaded_bytes") or 0) / tb if tb else 0.0
        overall = min(((item_idx - 1) + frac) / max(1, total), 1.0)
        label = f"{item_idx}/{total}" if pass_num == 1 else f"retry {item_idx}/{total}"
        speed = d.get("speed")
        if status == "downloading" and speed:
            label = f"{label}  {speed / 1_048_576:.1f} MiB/s"
        if progress_cb:
            progress_cb(overall, label)

    min_sec = MIN_TRACK_SECONDS if item.kind == "track" else 90
    if item.duration and item.duration > 45:
        min_sec = max(45, int(item.duration * 0.6))

    def _duration_filter(info_dict, *, incomplete=False, minimum=min_sec):
        if incomplete:
            return None
        if info_dict.get("is_live"):
            return "Skipping livestream"
        dur = info_dict.get("duration")
        if isinstance(dur, (int, float)) and dur < minimum:
            return f"Skipping short snippet/preview ({int(dur)}s < {minimum}s)"
        return None

    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "match_filter": _duration_filter,
        "progress_hooks": [_item_hook],
        "post_hooks": [item_files.append],
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    if ratelimit:
        ydl_opts["ratelimit"] = ratelimit
    if cookies_from_browser and cookies_from_browser != "none":
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)

    postprocessors: list[dict] = []
    if can_merge and audio_format != "best":
        pp: dict = {"key": "FFmpegExtractAudio", "preferredcodec": fmt}
        if fmt not in ("wav", "flac"):
            pp["preferredquality"] = kbps
        postprocessors.append(pp)
    if can_merge:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    if postprocessors:
        ydl_opts["postprocessors"] = postprocessors

    # Try the top-ranked full-length candidate URLs in order (up to 3 candidates per pass)
    for attempt_num, target_url in enumerate(candidate_urls[:3], start=1):
        if is_cancelled and is_cancelled():
            raise DownloadCancelled("cancelled")
        item_files.clear()
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                rc = ydl.download([target_url])
            downloaded = [p for p in item_files if os.path.exists(p)]
            if rc == 0 and downloaded:
                for p in downloaded:
                    if can_merge:
                        _write_id3_sidecar_tags(p, item, album_title)
                return downloaded
        except DownloadCancelled:
            raise
        except Exception as e:  # noqa: BLE001
            if attempt_num < min(3, len(candidate_urls)) and log_cb:
                log_cb(f"  candidate #{attempt_num} failed ({e}) — trying next full-length match …", "note")
            continue

    return []


def download_spotify(
    resolved: SpotifyResolved,
    *,
    out_dir: str,
    audio_format: str = "mp3",
    bitrate: Optional[str] = "192",
    playlist_numbering: bool = False,
    proxy: Optional[str] = None,
    ratelimit: Optional[int] = None,
    cookies_from_browser: Optional[str] = None,
    can_merge: bool = True,
    max_passes: int = 2,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    log_cb: Optional[Callable[[str, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    only_items: Optional[list[SpotifyItem]] = None,
) -> list[str]:
    """Download a resolved Spotify track, playlist, album, or podcast episode/show.

    Performs a two-pass verification loop (`max_passes=2`):
    - Pass 1 attempts all items using fast flat search + top 3 ranked full-track candidates.
    - If any songs fail in Pass 1, lists the failed tracks in the log and automatically
      runs Pass 2 ONLY on the failed items using broadened queries (`fallback_query` & `lyric_query`).
    """
    os.makedirs(out_dir, exist_ok=True)
    fmt = audio_format if audio_format and audio_format != "best" else "mp3"
    kbps = bitrate or "192"
    files: list[str] = []

    # 1. If `spotdl` CLI is installed and this is a music track/album/playlist (and not a selective retry), use spotdl
    if only_items is None and is_spotdl_installed() and resolved.kind in ("track", "album", "playlist") and can_merge:
        if log_cb:
            log_cb(f"spotdl found — downloading Spotify {resolved.kind}: {resolved.title}", "note")
        canonical = f"https://open.spotify.com/{resolved.kind}/{resolved.item_id}"
        cmd = [
            "spotdl", "download", canonical,
            "--format", fmt if fmt in ("mp3", "m4a", "flac", "wav", "opus") else "mp3",
            "--output", os.path.join(out_dir, "{artists} - {title}.{output-ext}"),
        ]
        if kbps and fmt in ("mp3", "m4a"):
            cmd += ["--bitrate", f"{kbps}k"]
        try:
            before = set(os.listdir(out_dir))
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                if is_cancelled and is_cancelled():
                    proc.terminate()
                    raise DownloadCancelled("cancelled")
                clean_line = line.strip()
                if clean_line and log_cb:
                    log_cb(clean_line, "note")
            rc = proc.wait()
            after = set(os.listdir(out_dir))
            new_files = [os.path.join(out_dir, f) for f in sorted(after - before)]
            if rc == 0 and new_files:
                if progress_cb:
                    progress_cb(1.0, "done")
                return new_files
        except DownloadCancelled:
            raise
        except Exception:  # noqa: BLE001
            if log_cb:
                log_cb("spotdl encountered an issue — falling back to OpenBand full-track resolver", "warn")

    # 2. Native OpenBand Multi-Pass Full-Track & Podcast Resolver
    pending: list[SpotifyItem] = list(
        only_items
        if only_items is not None
        else (
            resolved.items
            or [SpotifyItem(title=resolved.title, artist=resolved.creator, kind="track", index=1)]
        )
    )
    total_initial = max(1, len( resolved.items or pending ))

    for pass_num in range(1, max(1, max_passes) + 1):
        if not pending:
            break
        if is_cancelled and is_cancelled():
            raise DownloadCancelled("cancelled")

        if pass_num > 1:
            if log_cb:
                log_cb(
                    f"── PASS {pass_num}: retrying {len(pending)} failed song(s) with broadened search ──",
                    "warn",
                )
                for f_item in pending:
                    log_cb(f"  • #{f_item.index:02d} {f_item.artist} - {f_item.title}", "note")

        still_failed: list[SpotifyItem] = []
        batch_len = len(pending)

        for idx, item in enumerate(pending, start=1):
            if is_cancelled and is_cancelled():
                raise DownloadCancelled("cancelled")

            got_files = _download_single_spotify_item(
                item,
                idx=idx,
                total=batch_len,
                album_title=resolved.title,
                out_dir=out_dir,
                fmt=fmt,
                audio_format=audio_format,
                kbps=kbps,
                playlist_numbering=(total_initial > 1 and playlist_numbering),
                proxy=proxy,
                ratelimit=ratelimit,
                cookies_from_browser=cookies_from_browser,
                can_merge=can_merge,
                pass_num=pass_num,
                progress_cb=progress_cb,
                log_cb=log_cb,
                is_cancelled=is_cancelled,
            )
            if got_files:
                files.extend(got_files)
                if pass_num > 1 and log_cb:
                    log_cb(f"  + recovered on retry: {item.artist} - {item.title}", "ok")
            else:
                still_failed.append(item)
                if log_cb:
                    log_cb(f"  ! pass {pass_num} missed: #{item.index:02d} {item.artist} - {item.title}", "warn")

        pending = still_failed

    if pending and log_cb:
        log_cb(f"could not download {len(pending)} item(s) after {max_passes} passes:", "error")
        for miss in pending:
            log_cb(f"  × #{miss.index:02d} {miss.artist} - {miss.title}", "error")

    if progress_cb:
        progress_cb(1.0, "done")
    return files
