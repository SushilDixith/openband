"""knowledge — everything the app teaches. Pure data and functions: no UI, no yt-dlp.

Edit the wording here without touching any UI code. Anything numeric that depends on the
content of a video ("roughly half the size") is deliberately phrased as an approximation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# ════════════════════════════════════════════════════════════════════
#  small formatting helpers
# ════════════════════════════════════════════════════════════════════

def bars(n: int, width: int = 5) -> str:
    n = max(0, min(width, n))
    return "█" * n + "░" * (width - n)


def fmt_size(n: Optional[float]) -> str:
    if n is None:
        return "?"
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{max(n, 0) / 1e3:.0f} KB"


def fmt_duration(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return ""
    if seconds == 0:
        return "0:00"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ════════════════════════════════════════════════════════════════════
#  codecs
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CodecInfo:
    name: str
    short: str      # for tables
    tagline: str
    detail: str
    plays_on: str   # must stay short: it sits on one line of the card
    when: str
    compat: int     # 1-5: how widely it plays
    small: int      # 1-5: how small the files are for the same quality
    light: int      # 1-5: how light it is on CPU/GPU to play
    container: str  # what we put it in


CODECS: dict = {
    "auto": CodecInfo(
        name="AUTO", short="best",
        tagline="Best quality available — the codec is chosen for you.",
        detail=("yt-dlp takes the highest resolution on offer and, at that resolution, prefers the "
                "newest codecs (AV1, then VP9). You may end up with an MKV that older devices "
                "can't play. Pick H.264 if you want a file that works everywhere."),
        plays_on="depends on what is picked",
        when="Choose it when you only care about quality and your player is modern.",
        compat=0, small=0, light=0, container="MKV",
    ),
    "h264": CodecInfo(
        name="H.264 · AVC", short="universal",
        tagline="The safe choice. Plays on practically everything.",
        detail=("Phones, TVs, browsers, consoles and old laptops all decode it, usually in hardware. "
                "The trade-off: at the same visual quality its files are the biggest of the four. "
                "YouTube serves it up to 1080p; higher resolutions arrive as VP9 or AV1."),
        plays_on="everything",
        when="Pick it when you want a file that just works, anywhere.",
        compat=5, small=2, light=5, container="MP4",
    ),
    "h265": CodecInfo(
        name="H.265 · HEVC", short="newer devices",
        tagline="Roughly half the size of H.264 at similar quality.",
        detail=("Common in phone recordings and on streaming sites. Many recent phones, TVs and GPUs "
                "play it, but some browsers and older PCs need extra software or can't play it at all. "
                "YouTube rarely offers it, so it often won't be available."),
        plays_on="recent phones, TVs, PCs",
        when="Pick it to save space if you know your players support it.",
        compat=3, small=4, light=3, container="MP4",
    ),
    "vp9": CodecInfo(
        name="VP9", short="browsers, modern",
        tagline="YouTube's route to 1440p and 4K, with efficient files.",
        detail=("Google's open codec, similar in efficiency to H.265. Browsers and most modern players "
                "handle it; some older TVs and Apple devices may not. It usually lives in WebM or MKV "
                "rather than MP4."),
        plays_on="browsers, modern players",
        when="Pick it for 1440p / 4K on YouTube if your player supports it.",
        compat=4, small=4, light=3, container="MKV",
    ),
    "av1": CodecInfo(
        name="AV1", short="recent hardware",
        tagline="Newest and smallest, but it demands recent hardware.",
        detail=("The most efficient of the four, often giving the smallest files at a given quality. "
                "Smooth playback needs a recent GPU or phone (or a fast CPU); older machines may stutter "
                "or fail. We store it as MKV."),
        plays_on="recent devices only",
        when="Pick it to save the most space if your devices are recent.",
        compat=2, small=5, light=2, container="MKV",
    ),
    "other": CodecInfo(
        name="OTHER", short="varies",
        tagline="A less common codec.",
        detail="This stream uses a codec outside the usual four; compatibility varies.",
        plays_on="varies",
        when="",
        compat=0, small=0, light=0, container="MKV",
    ),
}
CODEC_KEYS = ("h264", "h265", "vp9", "av1")
CODEC_ORDER = ("av1", "vp9", "h265", "h264", "other")


def codec_key(codec: Optional[str]) -> str:
    return codec if codec in CODECS else "auto"


def codec_label(codec: Optional[str]) -> str:
    return {"h264": "H.264", "h265": "H.265", "vp9": "VP9", "av1": "AV1", "other": "OTHER"}.get(codec or "", "AUTO")


def container_for(codec: Optional[str]) -> str:
    return CODECS[codec_key(codec)].container


def ratings_line(codec: Optional[str]) -> str:
    c = CODECS[codec_key(codec)]
    if not c.compat:
        return ""
    return f"COMPAT {bars(c.compat)}   SMALL {bars(c.small)}   LIGHT {bars(c.light)}"


# ════════════════════════════════════════════════════════════════════
#  resolution & fps
# ════════════════════════════════════════════════════════════════════

RES_BANDS = [
    (144, "TINY", "Thumbnail-sized. Only for very slow connections."),
    (240, "LOW", "Very small and blocky; for slow connections or tiny screens."),
    (360, "SD", "Fine for a small phone screen; blurry on anything bigger."),
    (480, "SD", "Acceptable on a phone; soft on a laptop."),
    (720, "HD", "Sharp on phones and small laptops — a good balance of size and quality."),
    (1080, "FULL HD", "The standard for laptops, monitors and most TVs."),
    (1440, "QHD · 2K", "For large, sharp monitors. On YouTube it arrives as VP9 or AV1."),
    (2160, "4K · UHD", "For 4K TVs and editing. Big files: 4× the pixels of 1080p."),
    (4320, "8K", "Almost no device plays it smoothly. Enormous files."),
]


def res_band(height: int) -> tuple:
    chosen = RES_BANDS[0]
    for band in RES_BANDS:
        if band[0] <= height:
            chosen = band
    return chosen


def megapixels(height: int) -> float:
    return height * (height * 16 / 9) / 1e6  # assumes 16:9


# ════════════════════════════════════════════════════════════════════
#  audio
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AudioInfo:
    name: str
    tagline: str
    detail: str
    plays_on: str
    lossless: bool


AUDIO: dict = {
    "best": AudioInfo(
        "BEST · original", "Untouched original audio: best quality, no conversion.",
        ("Saves the stream exactly as the site stores it, usually Opus in .webm or AAC in .m4a. Nothing is "
         "re-encoded, so no quality is lost and ffmpeg isn't needed. Some older players can't open .webm / .opus."),
        "modern players; not every old device", False),
    "mp3": AudioInfo(
        "MP3", "Plays everywhere, in cars and on old players.",
        ("Re-encodes the audio, so it is lossy and never better than the source. A good pick for "
         "compatibility; the bitrate sets the size and the quality."),
        "everything", False),
    "m4a": AudioInfo(
        "M4A · AAC", "Efficient and widely supported; native on Apple devices.",
        ("Re-encoded to AAC, which usually sounds better than MP3 at the same bitrate. Works on phones, "
         "browsers and most players."),
        "phones, browsers, most players", False),
    "wav": AudioInfo(
        "WAV", "Uncompressed. Huge files, and no quality gain.",
        ("Stores raw audio at roughly 10 MB per minute. The source is already compressed, so WAV can't "
         "bring lost quality back; it is mainly useful for audio-editing software."),
        "everything (but huge)", True),
    "flac": AudioInfo(
        "FLAC", "Lossless compression of the decoded audio.",
        ("Roughly half the size of WAV with identical sound. It keeps exactly what the source decodes to, "
         "so it won't beat the original's quality, but it can be edited and re-saved without further loss."),
        "most players; not every phone or car", True),
}

BITRATE_NOTES = {
    128: "Fine for speech and casual listening.",
    192: "Good everyday music quality.",
    256: "Very good: hard to tell from the original.",
    320: "The ceiling for MP3. Largest files.",
}
DEFAULT_BITRATE = 192


def mb_per_minute(kbps: int) -> float:
    return kbps * 1000 / 8 * 60 / 1e6


# ════════════════════════════════════════════════════════════════════
#  lessons — shown in the LEARN panel for whatever is focused
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Lesson:
    title: str
    tagline: str = ""
    body: str = ""
    ratings: str = ""
    facts: str = ""  # video-specific line, only once a scan exists


@dataclass(frozen=True)
class ScanView:
    """The bits of a scan the lessons care about (so this module needn't know about yt-dlp)."""
    availability: dict   # codec family -> highest resolution
    heights: list        # all resolutions offered, high to low


def _availability_facts(scan: Optional[ScanView], only: Optional[str] = None) -> str:
    if not scan or not scan.availability:
        return ""
    order = ["h264", "h265", "vp9", "av1", "other"]
    if only is not None:
        have = scan.availability.get(only)
        if have:
            return f"THIS VIDEO ▸ {codec_label(only)} goes up to {have}p"
        return f"THIS VIDEO ▸ no {codec_label(only)} streams — yt-dlp will fall back to another codec"
    parts = [f"{codec_label(k)} ≤{scan.availability[k]}p" for k in order if k in scan.availability]
    return "THIS VIDEO ▸ " + "  ·  ".join(parts)


def learn(topic: str, value: Any = None, scan: Optional[ScanView] = None) -> Lesson:
    """Return the lesson for a form field. `value` is the field's current value."""
    if topic == "codec":
        key = codec_key(value if value != "none" else None)
        c = CODECS[key]
        facts = _availability_facts(scan, None if key == "auto" else key)
        return Lesson(c.name, c.tagline, c.detail + (" " + c.when if c.when else ""), ratings_line(key), facts)

    if topic == "res":
        if isinstance(value, int):
            label, use = res_band(value)[1:]
            mp = megapixels(value)
            ratio = mp / megapixels(1080)
            body = (f"About {mp:.1f} megapixels, {ratio:.2f}× the pixels of 1080p. File size grows roughly in "
                    f"step with pixel count, so each step up costs real disk space. Higher resolution also needs "
                    f"a screen that can show it: on a phone, 720p usually looks the same as 1080p.")
            facts = ""
            if scan and scan.heights:
                facts = "THIS VIDEO ▸ offers " + " ".join(f"{h}p" for h in scan.heights)
            return Lesson(f"{value}p · {label}", use, body, "", facts)
        facts = ""
        if scan and scan.heights:
            facts = "THIS VIDEO ▸ offers " + " ".join(f"{h}p" for h in scan.heights)
        return Lesson(
            "AUTO · highest available", "Download the sharpest picture the chosen codec offers.",
            "Choose a number to cap the quality and save space. Scan (F2) first to see which resolutions "
            "this particular video really has.", "", facts)

    if topic == "fps":
        if value:
            return Lesson(
                "60 FPS · smooth motion",
                "Noticeably smoother for sports, gaming and screen recordings.",
                "Typically needs 1.5–2× the data of 30 fps, and only exists for videos recorded that way. "
                "Many videos have no 60 fps version, and it is rare at low resolutions.")
        return Lesson(
            "30 FPS · standard",
            "Smooth enough for most video, with smaller files.",
            "Films run at 24 fps and most online video at 25–30. If a 60 fps stream exists at your "
            "resolution, leaving this off prefers the 30 fps one.")

    if topic == "mode":
        if value == "audio":
            return Lesson(
                "AUDIO ONLY", "Just the sound track.",
                "'BEST' keeps the original audio untouched and needs no extra tools. Converting to MP3, M4A, "
                "WAV or FLAC needs ffmpeg.")
        return Lesson(
            "VIDEO + AUDIO", "Picture and sound in one file.",
            "Sites store the best picture and the best sound as separate streams. ffmpeg merges them into one "
            "file; without ffmpeg only the lower-quality pre-merged streams are available (about 720p on YouTube).")

    if topic == "scope":
        if value == "playlist":
            return Lesson(
                "PLAYLIST", "Every video in the list.",
                "Downloads all items in order. Unavailable videos are skipped instead of stopping the run. "
                "Use 'INDEX - TITLE' naming (F7) to keep the order in the filenames.")
        return Lesson(
            "SINGLE VIDEO", "Just the video in the link.",
            "If the link also points into a playlist, only the one video is downloaded.")

    if topic == "aformat":
        key = value if value in AUDIO else "best"
        a = AUDIO[key]
        return Lesson(a.name, a.tagline, a.detail + f" Plays on: {a.plays_on}.")

    if topic == "bitrate":
        try:
            kbps = int(value)
        except (TypeError, ValueError):
            kbps = DEFAULT_BITRATE
        note = BITRATE_NOTES.get(kbps, "")
        return Lesson(
            f"{kbps} KBPS", note,
            f"Roughly {mb_per_minute(kbps):.1f} MB per minute. The site's own audio is typically around "
            f"128–160 kbps, so a higher bitrate mostly makes a bigger file, not a better one. "
            f"Bitrate doesn't apply to WAV, FLAC or 'BEST'.")

    if topic == "pattern":
        return Lesson(
            "FILE NAMING", "How downloads are named.",
            "TITLE uses the video title. INDEX - TITLE prefixes the playlist position (01, 02, …) so files "
            "sort in order. CUSTOM takes any yt-dlp output template.")
    if topic == "template":
        return Lesson("CUSTOM TEMPLATE", "A yt-dlp output template.",
                      "For example %(title)s.%(ext)s or %(uploader)s - %(title)s.%(ext)s.")
    if topic == "url":
        v_str = str(value or "").strip().lower().rstrip("/")
        from . import manifesto, platforms
        if v_str and platforms.is_manifesto_easter_egg(v_str):
            ui = manifesto._PAYLOAD["ui"]
            return Lesson(ui["lesson_title"], ui["lesson_tag"], ui["lesson_body"])
        if v_str and ("open.spotify.com" in v_str or v_str.startswith("spotify:")):
            return Lesson(
                "SPOTIFY LINK · SONG / PLAYLIST / PODCAST",
                "OpenBand resolves Spotify tracks, albums, playlists & podcast episodes without API keys.",
                "When you paste a Spotify link, OpenBand switches to AUDIO mode automatically, extracts track/episode "
                "metadata from Spotify, and downloads + tags each audio file via spotdl (if installed) or yt-dlp.")
        if v_str and ("instagram.com" in v_str or "instagr.am" in v_str):
            return Lesson(
                "INSTAGRAM LINK · REEL / POST / STORY",
                "Supports public Reels, video posts, multi-video carousels & authorized Stories.",
                "Instagram serves H.264/VP9 MP4 streams. For Stories, private reels, or rate-limited posts, open F7 → COOKIES "
                "and select your signed-in browser. Press F2 to inspect available resolutions or ENTER to download.")
        if v_str and any(h in v_str for h in ("x.com/", "twitter.com/", "t.co/", "vxtwitter.com/", "fxtwitter.com/")):
            return Lesson(
                "X (TWITTER) LINK · VIDEO POST / BROADCAST / SPACE",
                "Supports X status videos, multi-video posts, live broadcasts & audio Spaces.",
                "X serves HLS/MP4 video streams up to 1080p and AAC audio for Spaces. For age-restricted (NSFW) or protected "
                "posts you are entitled to view, select your browser under F7 → COOKIES.")
        if v_str and any(h in v_str for h in ("facebook.com/", "fb.watch/", "fb.com/")):
            return Lesson(
                "FACEBOOK LINK · WATCH / REEL / VIDEO",
                "Supports Facebook Watch, Reels, public page videos & /share/v/ links.",
                "Facebook serves SD/HD MP4 and DASH streams. For private, group, or age-gated videos you have access to, "
                "open F7 → COOKIES and select your signed-in browser.")
        return Lesson(
            "MEDIA LINK · YOUTUBE / SPOTIFY / INSTAGRAM / X / FACEBOOK",
            "Paste a YouTube, Spotify, Instagram, X (Twitter), Facebook, or web media URL.",
            "Platform is detected automatically. ENTER downloads straight away; F2 scans real formats, resolutions & "
            "creator metadata first; F3 opens the stream inspector.")
    if topic == "out":
        return Lesson("OUTPUT FOLDER", "Where files are saved.", "Leave empty to save in the current directory.")
    if topic == "limit":
        return Lesson("SPEED LIMIT", "Cap the download speed.",
                      "For example 1M is about 1 MB per second. Handy on a shared connection, or if a site "
                      "starts refusing you for going too fast.")
    if topic == "proxy":
        return Lesson("PROXY", "Route traffic through a proxy.",
                      "Format http://host:port. Useful for region-locked videos or restricted networks.")
    if topic == "archive":
        if value:
            return Lesson(
                "ARCHIVAL BUNDLE · ON",
                "Self-contained preservation copy with embedded metadata, chapters, thumbnail & subtitles.",
                "Bakes the creator name, upload date, chapter markers, cover art, and subtitles directly into the "
                "output container so your local copy remains complete even if the source page disappears.")
        return Lesson(
            "ARCHIVAL BUNDLE · OFF",
            "Standard media stream without extra embedded attachments.",
            "Enable ARCHIVE to embed chapters, cover thumbnail, subtitles, and metadata inside the file (requires ffmpeg).")
    if topic == "split":
        if value:
            return Lesson(
                "CHAPTER SPLITTER · ON",
                "Splits multi-chapter videos or albums into separate track files.",
                "Uses the video's chapter timestamps to cut the download into individual files alongside the main copy.")
        return Lesson(
            "CHAPTER SPLITTER · OFF",
            "Keeps the entire download as a single continuous file.",
            "Enable SPLIT when downloading full albums, concerts, or multi-part lectures with chapter markers.")
    if topic == "subs":
        if value == "transcript":
            return Lesson(
                "CLEAN TRANSCRIPT (.TXT)",
                "Downloads subtitles and strips timestamps/tags into a readable plain-text transcript.",
                "Saves a clean .transcript.txt alongside the media file — ideal for research, quotes, and offline reading.")
        if value in ("en", "all"):
            return Lesson(
                f"SUBTITLES · {str(value).upper()}",
                "Saves subtitle sidecar files (.vtt / .srt) alongside the media.",
                "EN grabs English (including auto-captions if needed); ALL pulls every available language track.")
        return Lesson(
            "SUBTITLES · OFF",
            "No separate subtitle files are written.",
            "Pick EN, ALL, or CLEAN TXT to harvest captions or generate a clean plain-text transcript.")
    if topic == "cookies":
        if value and value != "none":
            return Lesson(
                f"BROWSER COOKIES · {str(value).upper()}",
                "borrows your signed-in browser session to unlock restricted streams.",
                "Solves 'Confirm you are not a bot', age-restricted videos, and private/member-only streams.")
        return Lesson(
            "BROWSER COOKIES · NONE",
            "Anonymous public request without browser credentials.",
            "If YouTube blocks a download with a bot check or age gate, select your browser here.")
    if topic == "range":
        return Lesson(
            "TIME-RANGE CLIPPER",
            "Download only a specific time window (e.g. 01:20-04:15 or 90-180).",
            "Uses ffmpeg to cut the exact segment you need without downloading a multi-hour video. Leave empty for full length.")
    return Lesson("")


# ════════════════════════════════════════════════════════════════════
#  the "YOU'LL GET" summary
# ════════════════════════════════════════════════════════════════════

@dataclass
class Summary:
    spec: str
    plays: str
    size: Optional[int] = None
    notes: list = field(default_factory=list)
    warns: list = field(default_factory=list)


def video_warnings(codec: Optional[str], height: Optional[int], prefer60: bool, ffmpeg: bool) -> list:
    out = []
    if not ffmpeg:
        out.append("ffmpeg is missing, so video and audio can't be merged: only pre-merged streams "
                   "(up to ~720p on YouTube) are used. F1 shows how to fix it.")
    if codec == "h265":
        out.append("H.265 may not play in some browsers or on older PCs.")
    if codec == "av1":
        out.append("AV1 can stutter on older hardware.")
    if codec == "h264" and height and height > 1080:
        out.append("YouTube serves H.264 only up to 1080p, so expect 1080p.")
    if height and height >= 2160:
        out.append("4K files are big: 4× the pixels of 1080p.")
    if prefer60 and height and height <= 480:
        out.append("60 fps is rare at low resolutions.")
    return out


def describe_video(
    *, codec: Optional[str], height: Optional[int], prefer60: bool, ffmpeg: bool,
    row: Any = None, fell_back: bool = False, size: Optional[int] = None,
    offers: Optional[dict] = None,
) -> Summary:
    """`codec`/`height` are what the user asked for; `row` (if scanned) is what will be picked."""
    effective = row.codec if row is not None else codec
    shown_height = row.height if row is not None else height
    shown_fps = row.fps if row is not None else (60 if prefer60 else 30)
    info = CODECS[codec_key(effective)]

    container = container_for(effective) if ffmpeg else "single file"
    audio = "AAC" if effective in ("h264", "h265") else "Opus"
    spec = " · ".join([
        container,
        codec_label(effective),
        f"{shown_height}p" if shown_height else "best res",
        f"{shown_fps}fps" if row is not None or prefer60 else "≤30fps",
    ]) + f"  +  {audio}"

    s = Summary(spec=spec, plays=info.plays_on, size=size)
    if row is None:
        s.notes.append(info.tagline)
    else:
        if fell_back and codec:
            s.notes.append(f"This video has no {codec_label(codec)} stream at that size, so {codec_label(effective)} is used instead.")
        elif height and shown_height and shown_height < height:
            note = f"Best {codec_label(effective)} stream here is {shown_height}p."
            reach = [codec_label(k) for k in ("vp9", "av1", "h265", "h264")
                     if k != effective and (offers or {}).get(k, 0) >= height]
            if reach:
                note += f" {' or '.join(reach)} reach{'es' if len(reach) == 1 else ''} {height}p."
            s.notes.append(note)
        else:
            s.notes.append(info.tagline)
    s.warns = video_warnings(effective, shown_height, prefer60, ffmpeg)
    return s


def audio_warnings(fmt: str, kbps: Optional[int], ffmpeg: bool) -> list:
    out = []
    if fmt != "best" and not ffmpeg:
        out.append("ffmpeg is missing, so this format can't be made. Use BEST, or press F1 for help.")
    if fmt == "wav":
        out.append("WAV is huge (~10 MB per minute) and adds no quality.")
    if fmt in ("mp3", "m4a") and kbps and kbps >= 256:
        out.append("The source audio is typically ≤160 kbps: this bitrate mostly adds size.")
    return out


def describe_audio(
    *, fmt: str, bitrate: Optional[int], ffmpeg: bool, duration: Optional[int],
    src_codec: Optional[str] = None, src_size: Optional[int] = None,
) -> Summary:
    key = fmt if fmt in AUDIO else "best"
    info = AUDIO[key]
    kbps = bitrate or DEFAULT_BITRATE
    size = None
    if key == "best":
        spec = f"{src_codec or 'Opus / AAC'} · original stream, no re-encoding"
        size = src_size
    elif key in ("mp3", "m4a"):
        spec = f"{info.name} · {kbps} kbps"
        size = int(kbps * 1000 / 8 * duration) if duration else None
    elif key == "wav":
        spec = "WAV · uncompressed"
        size = int(1411 * 1000 / 8 * duration) if duration else None
    else:
        spec = "FLAC · lossless"
        size = int(1411 * 1000 / 8 * duration * 0.55) if duration else None
    s = Summary(spec=spec, plays=info.plays_on, size=size, notes=[info.tagline])
    s.warns = audio_warnings(key, bitrate if key in ("mp3", "m4a") else None, ffmpeg)
    return s


# ════════════════════════════════════════════════════════════════════
#  after-the-fact report: what did I ask for, what did I get, and why
# ════════════════════════════════════════════════════════════════════

def describe_got(g: Any) -> str:
    parts = []
    if g.codec:
        parts.append(codec_label(g.codec))
    if g.height:
        parts.append(f"{g.height}p")
    if g.fps and g.fps >= 50:
        parts.append(f"{g.fps}fps")
    if g.ext:
        parts.append(g.ext.upper())
    if g.acodec:
        parts.append(g.acodec)
    return " · ".join(parts) or "unknown"


def report_video(
    *, asked_codec: Optional[str], asked_height: Optional[int], asked_prefer60: bool,
    gots: Sequence[Any], availability: Optional[dict] = None,
) -> list:
    """Return [(text, level)] lines comparing what was requested with what was delivered."""
    if not gots:
        return []
    asked = " · ".join([codec_label(asked_codec), f"{asked_height}p" if asked_height else "best res"])
    counts = Counter(describe_got(g) for g in gots)
    got_text = "   ".join(f"{n}× {d}" if len(counts) > 1 or n > 1 else d for d, n in counts.most_common())
    lines = [(f"asked: {asked}", "note"), (f"got:   {got_text}", "info")]

    main = Counter(gots).most_common(1)[0][0]
    why = []
    if asked_codec and main.codec != asked_codec:
        have = (availability or {}).get(asked_codec)
        if availability is not None and not have:
            why.append(f"This video has no {codec_label(asked_codec)} stream, so {codec_label(main.codec)} was used.")
        elif have and asked_height and have < asked_height:
            why.append(f"{codec_label(asked_codec)} only goes up to {have}p here; {codec_label(main.codec)} was used for {main.height}p.")
        else:
            why.append(f"{codec_label(asked_codec)} wasn't offered for this video, so {codec_label(main.codec)} was used.")
    if asked_height and main.height and main.height < asked_height:
        why.append(f"No {asked_height}p stream exists for this video; {main.height}p was the best available.")
    if asked_prefer60 and main.fps and main.fps < 50:
        why.append("No 60 fps stream at this resolution.")
    lines += [(f"why:   {w}", "warn") for w in why[:2]]
    return lines
