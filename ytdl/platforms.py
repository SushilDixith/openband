"""platforms — multi-platform URL detection, extractor verification, and capability rules.

Supports YouTube, Spotify, Instagram, X (Twitter), Facebook, and generic yt-dlp extractors.
Kept free of Textual UI imports so it can be unit-tested independently.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional

try:
    import yt_dlp
    from yt_dlp.version import __version__ as YTDLP_VERSION
except ModuleNotFoundError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]
    YTDLP_VERSION = "not-installed"

import hashlib

from . import manifesto, spotify

__all__ = [
    "PlatformSpec",
    "PLATFORMS",
    "DetectedMedia",
    "detect_platform",
    "verify_extractor_support",
    "redact_secrets",
    "extract_creator_handle",
    "MANIFESTO_EASTER_EGGS",
    "is_manifesto_easter_egg",
]


@dataclass(frozen=True)
class PlatformSpec:
    key: str                  # "youtube" | "spotify" | "instagram" | "twitter" | "facebook" | "generic"
    name: str                 # Human-readable name: "YouTube", "Spotify", "Instagram", "X (Twitter)", "Facebook"
    badge: str                # Short badge for TUI headers: "YOUTUBE", "SPOTIFY", "INSTAGRAM", "X/TWITTER", "FACEBOOK"
    min_ytdlp: str            # Recommended minimum yt-dlp version for reliable extraction
    supports_video: bool
    supports_audio: bool
    supports_playlists: bool
    supports_chapters: bool
    supports_subtitles: bool
    supports_multi_codec: bool  # True if platform commonly offers AV1/VP9/H.264 choices (YouTube)
    auth_hint: str            # Guidance when authentication/cookies are needed


PLATFORMS: dict[str, PlatformSpec] = {
    "youtube": PlatformSpec(
        key="youtube",
        name="YouTube",
        badge="YOUTUBE",
        min_ytdlp="2024.04.09",
        supports_video=True,
        supports_audio=True,
        supports_playlists=True,
        supports_chapters=True,
        supports_subtitles=True,
        supports_multi_codec=True,
        auth_hint="Select your signed-in browser under F7 → COOKIES to unlock age-gated or member videos.",
    ),
    "spotify": PlatformSpec(
        key="spotify",
        name="Spotify",
        badge="SPOTIFY",
        min_ytdlp="2024.01.01",
        supports_video=False,
        supports_audio=True,
        supports_playlists=True,
        supports_chapters=False,
        supports_subtitles=False,
        supports_multi_codec=False,
        auth_hint="Spotify metadata resolves via public embeds; audio streams match via spotdl or yt-dlp.",
    ),
    "instagram": PlatformSpec(
        key="instagram",
        name="Instagram",
        badge="INSTAGRAM",
        min_ytdlp="2024.04.09",
        supports_video=True,
        supports_audio=True,
        supports_playlists=True,  # Multi-video carousels
        supports_chapters=False,
        supports_subtitles=False,
        supports_multi_codec=False,
        auth_hint="Instagram Stories, private reels, or rate-limited posts require F7 → COOKIES (signed-in browser).",
    ),
    "twitter": PlatformSpec(
        key="twitter",
        name="X (Twitter)",
        badge="X · TWITTER",
        min_ytdlp="2024.04.09",
        supports_video=True,
        supports_audio=True,
        supports_playlists=True,  # Multi-video posts
        supports_chapters=False,
        supports_subtitles=False,
        supports_multi_codec=False,
        auth_hint="Age-restricted or protected X posts and Spaces may require F7 → COOKIES (signed-in browser).",
    ),
    "facebook": PlatformSpec(
        key="facebook",
        name="Facebook",
        badge="FACEBOOK",
        min_ytdlp="2024.04.09",
        supports_video=True,
        supports_audio=True,
        supports_playlists=False,
        supports_chapters=False,
        supports_subtitles=True,
        supports_multi_codec=False,
        auth_hint="Private, group, or age-restricted Facebook videos require F7 → COOKIES (signed-in browser).",
    ),
    "openband": PlatformSpec(
        key="openband",
        name=manifesto._PAYLOAD["ui"]["name"],
        badge=manifesto._PAYLOAD["ui"]["badge"],
        min_ytdlp="2024.01.01",
        supports_video=False,
        supports_audio=False,
        supports_playlists=False,
        supports_chapters=False,
        supports_subtitles=False,
        supports_multi_codec=False,
        auth_hint="",
    ),
    "generic": PlatformSpec(
        key="generic",
        name="Web Media",
        badge="WEB STREAM",
        min_ytdlp="2024.01.01",
        supports_video=True,
        supports_audio=True,
        supports_playlists=True,
        supports_chapters=True,
        supports_subtitles=True,
        supports_multi_codec=True,
        auth_hint="If the site requires login, select your browser under F7 → COOKIES.",
    ),
}


@dataclass(frozen=True)
class DetectedMedia:
    platform: str             # key in PLATFORMS ("youtube", "spotify", "instagram", "twitter", "facebook", "generic", "invalid")
    kind: str                 # e.g. "video", "short", "playlist", "reel", "post", "story", "status", "space", "watch", "unsupported"
    item_id: str              # extracted ID if known, else ""
    canonical_url: str        # normalized URL
    supported: bool           # False if URL is a known non-media page (e.g., bare profile/login page) or invalid
    reason: str = ""          # If not supported or needs cookies, human-readable explanation
    requires_cookies: bool = False

    @property
    def spec(self) -> PlatformSpec:
        return PLATFORMS.get(self.platform, PLATFORMS["generic"])

    @property
    def label(self) -> str:
        if self.platform == "invalid":
            return "INVALID URL"
        return f"{self.spec.badge} · {self.kind.upper()}"


# ── Regexes for URL classification ──────────────────────────────────

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"}
_TWITTER_HOSTS = {"twitter.com", "www.twitter.com", "mobile.twitter.com", "x.com", "www.x.com", "mobile.x.com", "vxtwitter.com", "fxtwitter.com", "fixupx.com"}
_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.watch", "www.fb.watch", "fb.com", "www.fb.com"}

# Instagram paths: /reel/<id>, /reels/<id>, /p/<id>, /tv/<id>, /stories/<user>/<id>
_IG_REEL_POST_RE = re.compile(r"^/(?:[a-zA-Z0-9_.-]+/)?(reel|reels|p|tv)/([A-Za-z0-9_-]+)", re.I)
_IG_STORY_RE = re.compile(r"^/stories/([A-Za-z0-9_.-]+)(?:/(\d+))?", re.I)
_IG_NON_MEDIA_PATHS = {"explore", "accounts", "direct", "about", "legal", "directory"}

# X / Twitter paths: /<user>/status/<id>, /i/web/status/<id>, /i/spaces/<id>, /i/broadcasts/<id>
_TW_STATUS_RE = re.compile(r"^/(?:[A-Za-z0-9_]+|i/web)/status(?:es)?/(\d+)", re.I)
_TW_SPACE_RE = re.compile(r"^/i/spaces/([A-Za-z0-9]+)", re.I)
_TW_BROADCAST_RE = re.compile(r"^/i/broadcasts/([A-Za-z0-9]+)", re.I)
_TW_NON_MEDIA_PATHS = {"home", "explore", "notifications", "messages", "settings", "search", "login", "i"}

# Facebook paths: /watch/?v=<id>, /reel/<id>, /<user>/videos/<id>, /video.php?v=<id>, /share/v/<id>, /share/r/<id>, /stories/<id>
_FB_REEL_RE = re.compile(r"^/reel/([A-Za-z0-9_-]+)", re.I)
_FB_VIDEO_RE = re.compile(r"^/(?:[^/]+/)?videos/(?:[^/]+/)?(\d+)", re.I)
_FB_SHARE_RE = re.compile(r"^/share/(v|r)/([A-Za-z0-9_-]+)", re.I)
_FB_STORY_RE = re.compile(r"^/stories/([A-Za-z0-9_.-]+)", re.I)


def _normalize_x_url(url: str, parsed: urllib.parse.ParseResult) -> str:
    """Normalize vxtwitter/fxtwitter/fixupx or mobile.twitter.com links to standard x.com/twitter.com."""
    host = (parsed.hostname or "").lower()
    if host in ("vxtwitter.com", "fxtwitter.com", "fixupx.com"):
        return urllib.parse.urlunparse(parsed._replace(netloc="x.com"))
    return url



# Obfuscated SHA-256 carrier frequency signatures (no plaintext trigger strings in source)
_SCHEME_SIG = "b725da84773a3b30"
_CARRIER_SIGS: frozenset[str] = frozenset((
    "0a9c9dd6be2788f54c364994",
    "6b5c1433a5bbfd8433890745",
    "711a23e6b427b1ff9df7fa89",
    "856e0cd02f3352d6b5b2b641",
    "918fe47bf373e20fa13e1e97",
    "98d329c8d827e86ee267f31a",
    "af9341b630199f316345c548",
    "c2b5f2d5ad8b9288946c2f66",
    "c98d6dbd3c44b01e5ea5d19d",
    "dd7e692de7d97868a4bb457a",
    "fa9f79240c9845bbc43186fb",
))
MANIFESTO_EASTER_EGGS: tuple[str, ...] = tuple(_CARRIER_SIGS)


def is_manifesto_easter_egg(url: str) -> bool:
    """Verify whether `url` matches an obfuscated SHA-256 carrier signature."""
    raw = (url or "").strip().lower().rstrip("/")
    if not raw:
        return False
    sig = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    if sig in _CARRIER_SIGS:
        return True
    if "://" in raw:
        scheme = raw.split("://", 1)[0]
        if hashlib.sha256(scheme.encode("utf-8")).hexdigest()[:16] == _SCHEME_SIG:
            return True
    return False


def detect_platform(url: str) -> DetectedMedia:
    """Inspect a user-supplied URL and automatically classify its platform, media type, and support status."""
    raw = (url or "").strip()
    if not raw:
        return DetectedMedia("invalid", "empty", "", "", False, "Paste a media link first.")

    # 0. Check obfuscated carrier signature
    if is_manifesto_easter_egg(raw):
        ui = manifesto._PAYLOAD["ui"]
        return DetectedMedia(
            "openband",
            "carrier",
            "00",
            ui["cat_url"],
            True,
            reason=ui["reason"],
        )

    # 1. Check Spotify URLs & URIs first
    sp = spotify.parse_spotify_url(raw)
    if sp:
        sp_kind, sp_id = sp
        return DetectedMedia("spotify", sp_kind, sp_id, raw, True)

    # Ensure scheme for URL parsing
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        return DetectedMedia(
            "invalid", "invalid", "", raw, False,
            "That doesn't look like a valid URL. Paste a full link starting with https://",
        )

    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:  # noqa: BLE001
        return DetectedMedia("invalid", "invalid", "", raw, False, "Malformed URL.")

    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    query = urllib.parse.parse_qs(parsed.query)

    if not host or "." not in host:
        return DetectedMedia("invalid", "invalid", "", raw, False, "Missing domain name in URL.")

    # 2. YouTube
    if host in _YOUTUBE_HOSTS or host.endswith(".youtube.com"):
        if host in ("youtu.be", "www.youtu.be"):
            vid = path.strip("/").split("/")[0]
            if not vid:
                return DetectedMedia("youtube", "unsupported", "", raw, False, "YouTube short-link is missing a video ID.")
            return DetectedMedia("youtube", "video", vid, raw, True)
        if path.startswith("/shorts/"):
            vid = path.split("/shorts/", 1)[1].split("/")[0]
            return DetectedMedia("youtube", "short", vid, raw, bool(vid), "" if vid else "Missing YouTube Shorts ID.")
        if path.startswith("/playlist") and "list" in query:
            return DetectedMedia("youtube", "playlist", query["list"][0], raw, True)
        if "v" in query and query["v"]:
            kind = "playlist" if "list" in query else "video"
            return DetectedMedia("youtube", kind, query["v"][0], raw, True)
        if path.startswith(("/live/", "/embed/", "/v/", "/clip/")):
            parts = [p for p in path.split("/") if p]
            vid = parts[1] if len(parts) > 1 else ""
            return DetectedMedia("youtube", parts[0], vid, raw, bool(vid))
        if path.startswith(("/@", "/channel/", "/c/", "/user/")):
            return DetectedMedia("youtube", "channel", path.strip("/"), raw, True)
        return DetectedMedia(
            "youtube", "unsupported", "", raw, False,
            "Paste a direct YouTube video, Short, or playlist URL rather than the home page.",
        )

    # 3. Instagram
    if host in _INSTAGRAM_HOSTS or host.endswith(".instagram.com"):
        m_post = _IG_REEL_POST_RE.match(path)
        if m_post:
            raw_kind, ig_id = m_post.group(1).lower(), m_post.group(2)
            kind = "reel" if raw_kind in ("reel", "reels") else ("igtv" if raw_kind == "tv" else "post")
            return DetectedMedia("instagram", kind, ig_id, raw, True)
        m_story = _IG_STORY_RE.match(path)
        if m_story:
            user, story_id = m_story.group(1), m_story.group(2) or user
            return DetectedMedia(
                "instagram", "story", story_id, raw, True,
                reason="Instagram Stories require a signed-in browser session (F7 → COOKIES).",
                requires_cookies=True,
            )
        first_seg = path.strip("/").split("/")[0].lower() if path.strip("/") else ""
        if not first_seg or first_seg in _IG_NON_MEDIA_PATHS:
            return DetectedMedia(
                "instagram", "unsupported", "", raw, False,
                "Unsupported Instagram page. Paste a direct Reel (/reel/...), Post (/p/...), or Story (/stories/...) link.",
            )
        return DetectedMedia(
            "instagram", "unsupported", first_seg, raw, False,
            f"Instagram profile links (@{first_seg}) cannot be downloaded directly — paste a specific Reel (/reel/...) or Post (/p/...) URL.",
        )

    # 4. X (Twitter)
    if host in _TWITTER_HOSTS or host == "t.co":
        if host == "t.co":
            code = path.strip("/").split("/")[0]
            return DetectedMedia("twitter", "shortlink", code, raw, bool(code), "" if code else "Empty t.co shortlink.")
        norm_url = _normalize_x_url(raw, parsed)
        m_status = _TW_STATUS_RE.match(path)
        if m_status:
            return DetectedMedia("twitter", "status", m_status.group(1), norm_url, True)
        m_space = _TW_SPACE_RE.match(path)
        if m_space:
            return DetectedMedia("twitter", "space", m_space.group(1), norm_url, True)
        m_bcast = _TW_BROADCAST_RE.match(path)
        if m_bcast:
            return DetectedMedia("twitter", "broadcast", m_bcast.group(1), norm_url, True)
        first_seg = path.strip("/").split("/")[0].lower() if path.strip("/") else ""
        if not first_seg or first_seg in _TW_NON_MEDIA_PATHS:
            return DetectedMedia(
                "twitter", "unsupported", "", norm_url, False,
                "Unsupported X (Twitter) page. Paste a direct post link (x.com/<user>/status/<id>) or Space link.",
            )
        return DetectedMedia(
            "twitter", "unsupported", first_seg, norm_url, False,
            f"X profile links (@{first_seg}) aren't single media items — paste a direct post URL (x.com/{first_seg}/status/...).",
        )

    # 5. Facebook
    if host in _FACEBOOK_HOSTS or host.endswith(".facebook.com"):
        if host in ("fb.watch", "www.fb.watch"):
            code = path.strip("/").split("/")[0]
            return DetectedMedia(
                "facebook", "watch", code, raw, bool(code),
                "" if code else "Incomplete fb.watch short-link.",
            )
        if path.startswith("/watch") and ("v" in query or path.strip("/") != "watch"):
            vid = (query.get("v") or [path.strip("/").split("/")[-1]])[0]
            return DetectedMedia("facebook", "watch", vid, raw, True)
        if path.startswith("/video.php") and "v" in query:
            return DetectedMedia("facebook", "video", query["v"][0], raw, True)
        m_reel = _FB_REEL_RE.match(path)
        if m_reel:
            return DetectedMedia("facebook", "reel", m_reel.group(1), raw, True)
        m_vid = _FB_VIDEO_RE.match(path)
        if m_vid:
            return DetectedMedia("facebook", "video", m_vid.group(1), raw, True)
        m_share = _FB_SHARE_RE.match(path)
        if m_share:
            s_type, s_id = m_share.group(1).lower(), m_share.group(2)
            return DetectedMedia("facebook", "reel" if s_type == "r" else "video", s_id, raw, True)
        m_story = _FB_STORY_RE.match(path)
        if m_story:
            return DetectedMedia(
                "facebook", "story", m_story.group(1), raw, True,
                reason="Facebook Stories require a signed-in browser session (F7 → COOKIES).",
                requires_cookies=True,
            )
        if "/posts/" in path or "story_fbid" in query:
            vid = (query.get("story_fbid") or [path.strip("/").split("/")[-1]])[0]
            return DetectedMedia("facebook", "post", vid, raw, True)
        return DetectedMedia(
            "facebook", "unsupported", "", raw, False,
            "Unsupported Facebook URL. Paste a direct video (/watch?v=..., /videos/...), Reel (/reel/...), or share link.",
        )

    # 6. Generic HTTP(S) media link supported by yt-dlp's other extractors
    return DetectedMedia("generic", "stream", "", raw, True)


def verify_extractor_support(platform_key: str) -> tuple[bool, str]:
    """Verify whether the installed yt-dlp version has extractor support for `platform_key`."""
    spec = PLATFORMS.get(platform_key, PLATFORMS["generic"])
    if platform_key == "spotify":
        return True, "Spotify metadata & duration-verified audio matcher ready."
    if yt_dlp is None:
        return False, "yt-dlp is not installed."

    extractor_Map = {
        "youtube": "Youtube",
        "instagram": "Instagram",
        "twitter": "Twitter",
        "facebook": "Facebook",
    }
    needle = extractor_Map.get(platform_key)
    if needle:
        try:
            from yt_dlp.extractor import gen_extractor_classes
            found = any(needle.lower() in getattr(ie, "IE_NAME", "").lower() for ie in gen_extractor_classes())
            if not found:
                return False, f"Installed yt-dlp ({YTDLP_VERSION}) is missing the {spec.name} extractor — press F9 to update."
        except Exception:  # noqa: BLE001
            pass

    return True, f"{spec.name} extractor ready (yt-dlp {YTDLP_VERSION})"


_SECRET_PATTERNS = [
    (re.compile(r"(--cookies\s+)(\S+)", re.I), r"\1[REDACTED_COOKIE_FILE]"),
    (re.compile(r"(sessionid|auth_token|ct0|ds_user_id|c_user|xs|Bearer\s+)[=:\s]*[A-Za-z0-9._%-]{6,}", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(Cookie:\s*)[^\r\n]+", re.I), r"\1[REDACTED]"),
]


def redact_secrets(text: str) -> str:
    """Ensure session cookies, tokens, or credentials are never logged or leaked to UI logs."""
    out = str(text or "")
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def extract_creator_handle(info: dict, detected: Optional[DetectedMedia] = None) -> str:
    """Extract the most descriptive creator/author attribution from a yt-dlp info_dict."""
    channel = str(info.get("channel") or "").strip()
    uploader = str(info.get("uploader") or "").strip()
    uploader_id = str(info.get("uploader_id") or "").strip()

    if uploader_id and not uploader_id.startswith("@") and detected and detected.platform in ("twitter", "instagram"):
        handle = f"@{uploader_id}"
    elif uploader_id and uploader_id.startswith("@"):
        handle = uploader_id
    else:
        handle = ""

    primary = channel or uploader
    if primary and handle and handle.lower() not in primary.lower():
        return f"{primary} ({handle})"
    return primary or handle or (detected.spec.name if detected else "")
