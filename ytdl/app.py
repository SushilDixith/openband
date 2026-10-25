"""app — the OpenBand Textual interface.

Includes:
- Automatic multi-platform detection: YouTube, Spotify, Instagram, X (Twitter), Facebook & web streams
- Cinematic opening sequence (skippable via ENTER/SPACE/ESC or --fast / OPENBAND_NO_SPLASH=1)
- Editorial OpenBand masthead, time-aware operator greeting & persistent plate/quote rotation
- Dynamic option gating based on platform & scanned media capabilities
- Non-blocking download queue with animated signal transmission pulse
- Archival Bundle (metadata, chapters, thumbnail, subs) & Chapter Splitter
- Subtitle & Clean Transcript (.txt) Harvester
- Browser Cookie Unlocker (with credential redaction) & Time-Range Clipper
- Commons Catalog modal (F4), Live CLI Command Preview (F10), Clipboard Paste & Scan (^G),
  Batch Importer (^B), and Presets (Alt+1..4)
- Memorable movement exit banner on quit
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import threading
from collections import Counter, deque
from dataclasses import dataclass
from typing import Optional

try:
    import yt_dlp
except ModuleNotFoundError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Checkbox, Footer, Input, Label, RadioButton, RadioSet, RichLog, Rule, Select, Static

from . import core, knowledge as kb, manifesto, platforms, spotify
from .screens import BatchImportScreen, CatalogScreen, FormatScreen, ManifestoScreen
from .theme import AMBER, BRIGHT, CSS, DIM, ORANGE, PHOSPHOR, RED, SIGNAL
from .widgets import Gauge, ManifestoBanner, Panel

# ── form options ────────────────────────────────────────────────────
PATTERNS = [("TITLE", "title"), ("INDEX - TITLE", "index"), ("CUSTOM", "custom")]
CODEC_OPTIONS = [("AUTO", "none"), ("H.264", "h264"), ("H.265", "h265"), ("VP9", "vp9"), ("AV1", "av1")]
AUDIO_OPTIONS = [(f.upper(), f) for f in ("best", "mp3", "m4a", "wav", "flac")]
BITRATE_OPTIONS = [("DEFAULT", "default")] + [(b, b) for b in ("128", "192", "256", "320")]
SUBS_OPTIONS = [("OFF", "off"), ("EN SUBS", "en"), ("ALL SUBS", "all"), ("CLEAN TXT", "transcript")]
COOKIE_OPTIONS = [(b.upper(), b) for b in core.BROWSERS]

# which form widget teaches which topic
TOPIC_IDS = {
    "url": "url", "out": "out", "pattern": "pattern", "template": "template", "scope": "scope",
    "mode": "mode", "codec": "codec", "res": "res", "fps": "fps", "aformat": "aformat",
    "bitrate": "bitrate", "limit": "limit", "proxy": "proxy",
    "archive": "archive", "split": "split", "subs": "subs", "cookies": "cookies", "range": "range",
}

# level -> (style, line marker)
LOG_STYLES = {
    "info": (AMBER, "  "),
    "note": (DIM, "· "),
    "ok": (f"bold {SIGNAL}", "✓ "),
    "warn": (ORANGE, "! "),
    "error": (f"bold {RED}", "× "),
}
CARD_WIDTH = 56
ROTATION_SECONDS = 45.0


def row(key: str, *children, id: Optional[str] = None, classes: str = "") -> Horizontal:
    """One aligned form row: fixed-width key column, then fields."""
    return Horizontal(Label(key, classes="key"), *children, id=id, classes=f"row {classes}".strip())


def sub(text: str) -> Label:
    return Label(text, classes="sub")


def trunc(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


@dataclass
class Selection:
    audio: bool
    codec: Optional[str]
    height: Optional[int]
    prefer60: bool
    aformat: str
    bitrate: Optional[int]
    archive_bundle: bool
    split_chapters: bool
    subs_mode: str
    cookies: Optional[str]
    time_range: Optional[str]


@dataclass
class QueuedJob:
    options: core.DownloadOptions
    availability: Optional[dict]
    title_hint: str
    channel_hint: str
    spec_hint: str


# ── worker -> UI messages ───────────────────────────────────────────

class LogLine(Message):
    def __init__(self, text: str, level: str = "info", toast: bool = False):
        super().__init__()
        self.text, self.level, self.toast = text, level, toast


class ProgressUpdate(Message):
    def __init__(self, fraction: float, label: str):
        super().__init__()
        self.fraction, self.label = fraction, label


class ScanDone(Message):
    def __init__(self, scan: core.ScanData):
        super().__init__()
        self.scan = scan


class FolderKnown(Message):
    def __init__(self, path: str):
        super().__init__()
        self.path = path


class UpdateAvailable(Message):
    def __init__(self, version: str):
        super().__init__()
        self.version = version


class JobDone(Message):
    pass


# ── app ─────────────────────────────────────────────────────────────

class YtdlApp(App):
    TITLE = "OPENBAND · A MOVEMENT FOR FREE MEDIA"
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS

    BINDINGS = [
        Binding("f2", "scan", "SCAN", key_display="F2"),
        Binding("f3", "formats", "FORMATS", key_display="F3"),
        Binding("f4", "catalog", "CATALOG", key_display="F4"),
        Binding("f5", "download", "DOWNLOAD", key_display="F5"),
        Binding("escape", "cancel", "CANCEL", key_display="ESC"),
        Binding("f6", "open_folder", "OPEN", key_display="F6"),
        Binding("f7", "more", "OPTIONS", key_display="F7"),
        Binding("f8", "cycle_art", "PLATE", key_display="F8"),
        Binding("f10", "copy_cli", "CLI", key_display="F10"),
        Binding("ctrl+g", "paste_scan", "PASTE&SCAN", key_display="^G"),
        Binding("ctrl+b", "batch_import", "BATCH", key_display="^B"),
        Binding("alt+1", "preset_1", "MP4", show=False),
        Binding("alt+2", "preset_2", "ARCHIVE", show=False),
        Binding("alt+3", "preset_3", "MP3", show=False),
        Binding("alt+4", "preset_4", "FLAC", show=False),
        Binding("f9", "update", "UPDATE", key_display="F9"),
        Binding("f1", "setup", "SETUP", key_display="F1"),
        Binding("ctrl+q", "quit", "QUIT", key_display="^Q"),
    ]

    def __init__(
        self,
        start_scene: Optional[int] = None,
        show_splash: Optional[bool] = None,
        initial_urls: Optional[list[str]] = None,
        initial_preset: Optional[str] = None,
    ):
        super().__init__()
        self.register_theme(PHOSPHOR)
        self.theme = "phosphor"
        self.diag = core.diagnose()
        self.scan: Optional[core.ScanData] = None
        self.busy = False
        self.cancel_event = threading.Event()
        self.update_version: Optional[str] = None
        self.last_dir: Optional[str] = None
        self.topic = "url"
        self.presets = core.load_presets()
        self.job_queue: deque[QueuedJob] = deque()
        self.active_preset_name: Optional[str] = None

        # Advance and persist scene & quote on every application launch
        if start_scene is None:
            s_idx, q_idx, sessions = manifesto.next_startup_state()
        else:
            s_idx, q_idx, sessions = start_scene, start_scene, 1
        self.scene_index = s_idx
        self.quote_index = q_idx
        self.session_number = sessions
        self.greeting = manifesto.build_greeting(session_number=sessions)

        self.initial_urls: list[str] = list(initial_urls or [])
        self.initial_preset: Optional[str] = initial_preset

        if show_splash is None:
            no_splash_env = os.environ.get("OPENBAND_NO_SPLASH", "").strip().lower()
            self.show_splash = (no_splash_env not in ("1", "true", "yes")) and not self.initial_urls
        else:
            self.show_splash = show_splash

    # ---- layout --------------------------------------------------------

    def compose(self) -> ComposeResult:
        comp = manifesto.get_composition(self.scene_index, self.quote_index)
        logo = Text.assemble(
            ("((●)) ", SIGNAL),
            ("O P E N B A N D", f"bold {BRIGHT}"),
            ("  ·  ", DIM),
            (comp.slogan, f"bold {SIGNAL}"),
        )
        yield Horizontal(Static(logo, id="logo"), Static(self.env_text(), id="env"), id="head")
        yield Static(Text.assemble(("▸ ", SIGNAL), (self.greeting, f"bold {BRIGHT}")), id="greet-bar")
        yield Rule(line_style="heavy")

        # Symmetrical 2-column top deck: Left (#left-col) and Right (#right-col) share exact height: 13
        with Horizontal(id="top"):
            with Vertical(id="left-col"):
                yield row(
                    "URL",
                    Input(
                        id="url",
                        placeholder="paste YouTube, Spotify, Instagram, X (Twitter), or Facebook URL · ENTER downloads · F2 scans",
                    ),
                )
                yield row("OUT", Input(id="out", placeholder="current directory (.) — local user-owned archive"))
                yield row(
                    "SCOPE",
                    RadioSet(RadioButton("SINGLE", value=True), RadioButton("PLAYLIST"), id="scope"),
                    Checkbox("ARCHIVE", id="archive"),
                    Checkbox("SPLIT", id="split"),
                    classes="gap",
                )
                yield row("MODE", RadioSet(RadioButton("VIDEO", value=True), RadioButton("AUDIO"), id="mode"))
                with Vertical(id="opts"):
                    yield row(
                        "VIDEO",
                        Select(CODEC_OPTIONS, value="h264", allow_blank=False, id="codec"),
                        sub("RES"), Select([("AUTO", "auto")], value="auto", allow_blank=False, id="res"),
                        Checkbox("60FPS", id="fps"),
                        id="video-row",
                    )
                    yield row(
                        "AUDIO",
                        Select(AUDIO_OPTIONS, value="best", allow_blank=False, id="aformat"),
                        sub("BITRATE"), Select(BITRATE_OPTIONS, value="default", allow_blank=False, id="bitrate"),
                        id="audio-row",
                    )
                yield Static(
                    "▸ F7  subs · cookies · range · limit · proxy   ·   Alt+1..4 presets",
                    id="morehint",
                    classes="hint gap",
                )
                with Vertical(id="more"):
                    yield row(
                        "NAME",
                        Select(PATTERNS, value="title", allow_blank=False, id="pattern"),
                        Input(value="%(title)s.%(ext)s", id="template", disabled=True),
                    )
                    yield row(
                        "SUBS",
                        Select(SUBS_OPTIONS, value="off", allow_blank=False, id="subs"),
                        sub("COOKIES"),
                        Select(COOKIE_OPTIONS, value="none", allow_blank=False, id="cookies"),
                    )
                    yield row(
                        "RANGE",
                        Input(id="range", placeholder="01:20-04:15"),
                        sub("LIMIT"),
                        Input(id="limit", placeholder="2M"),
                        sub("PROXY"),
                        Input(id="proxy", placeholder="http://host:port"),
                    )
            yield ManifestoBanner(initial_index=self.scene_index, initial_quote=self.quote_index, id="right-col")

        # Symmetrical 2-column middle deck: OUTPUT PREVIEW (left) + FIELD GUIDE (right) share exact height: 7
        with Horizontal(id="mid"):
            yield Panel("OUTPUT PREVIEW", id="card")
            yield Panel("FIELD GUIDE", id="learn")

        yield row("SIGNAL", Gauge(id="gauge"), id="prog-row")
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self._update_left_col_subtitle()
        self.query_one("#more").display = False
        log_widget = self.query_one("#log", RichLog)
        log_widget.border_title = "TRANSMISSION & ARCHIVE LOG"
        log_widget.border_subtitle = "REAL-TIME TELEMETRY"
        self.sync_mode()
        self.query_one("#url", Input).focus()
        self.refresh_card()
        self.refresh_learn("url")

        comp = manifesto.get_composition(self.scene_index, self.quote_index)
        self.write_log(self.greeting, "ok")
        self.write_log(f'[{comp.artwork.title}] "{comp.quote}" {comp.attribution}', "note")
        if not self.diag.ffmpeg:
            self.write_log("ffmpeg not found — HD merging, clipping, and archival bundling are limited (F1)", "warn")
        if not self.diag.js:
            self.write_log("no JS runtime (deno / node) — some YouTube formats may be missing (F1)", "warn")
        self.check_update_worker()

        if self.initial_preset and self.initial_preset in self.presets:
            self._apply_preset(self.initial_preset)
        if self.initial_urls:
            self._enqueue_url_list(self.initial_urls)
        elif self.show_splash:
            self._open_manifesto_screen(start_with_letter=False)

        self.set_interval(ROTATION_SECONDS, self._auto_rotate_art)
        self.set_interval(0.35, self._pulse_gauge)

    def _pulse_gauge(self) -> None:
        if self.busy:
            gauge = self.query_one("#gauge", Gauge)
            gauge.tick += 1

    def _update_left_col_subtitle(self) -> None:
        left_col = self.query_one("#left-col")
        left_col.border_title = "((●)) SIGNAL ACQUISITION DESK"
        q_len = len(self.job_queue)
        url_val = self.val("url") if self.is_mounted else ""
        detected = platforms.detect_platform(url_val) if url_val else None

        if q_len > 0:
            left_col.border_subtitle = f"QUEUE: {q_len} PENDING · ESC CANCEL"
        elif self.active_preset_name:
            left_col.border_subtitle = f"PRESET: {self.active_preset_name.upper()}"
        elif detected and detected.platform != "invalid":
            left_col.border_subtitle = f"DETECTED: {detected.label} · ENTER ACQUIRE · F2 SCAN"
        else:
            left_col.border_subtitle = "ENTER ACQUIRE · F2 INSPECT · F4 CATALOG"

    def _update_masthead_slogan(self) -> None:
        comp = manifesto.get_composition(self.scene_index, self.quote_index)
        logo = Text.assemble(
            ("((●)) ", SIGNAL),
            ("O P E N B A N D", f"bold {BRIGHT}"),
            ("  ·  ", DIM),
            (comp.slogan, f"bold {SIGNAL}"),
        )
        self.query_one("#logo", Static).update(logo)

    def _auto_rotate_art(self) -> None:
        if not self.busy:
            banner = self.query_one("#right-col", ManifestoBanner)
            banner.next_scene()
            self.scene_index = banner.scene_index
            self.quote_index = banner.quote_index
            self._update_masthead_slogan()
            manifesto.save_state({
                "scene_index": self.scene_index,
                "quote_index": self.quote_index,
                "sessions": self.session_number,
            })

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 106, "narrow")

    # ---- small helpers -------------------------------------------------

    def env_text(self) -> Text:
        d = self.diag
        t = Text(no_wrap=True)
        t.append("YT-DLP ", style=DIM)
        t.append(d.ytdlp, style=AMBER)
        if self.update_version:
            t.append(f" ▲{self.update_version}(F9)", style=ORANGE)
        t.append("  ·  FFMPEG ", style=DIM)
        t.append("● OK", style=BRIGHT) if d.ffmpeg else t.append("○ MISSING", style=RED)
        t.append("  ·  JS ", style=DIM)
        t.append(f"● {d.js.upper()}", style=BRIGHT) if d.js else t.append("○ NONE", style=ORANGE)
        t.append("  ·  PLATFORMS ", style=DIM)
        t.append("● YT·IG·X·FB·SP", style=BRIGHT)
        return t

    def val(self, widget_id: str) -> str:
        return str(self.query_one(f"#{widget_id}").value).strip()

    def write_log(self, text: str, level: str = "info") -> None:
        style, mark = LOG_STYLES.get(level, LOG_STYLES["info"])
        self.query_one("#log", RichLog).write(Text(mark + core.clean(text), style=style))

    def warn(self, text: str) -> None:
        self.write_log(text, "warn")
        self.notify(text, severity="warning", timeout=4)

    def set_gauge(self, fraction: float, label: str) -> None:
        gauge = self.query_one("#gauge", Gauge)
        gauge.fraction = fraction
        gauge.label = label

    def selection(self) -> Selection:
        codec = self.val("codec")
        res = self.query_one("#res", Select).value
        bitrate = self.val("bitrate")
        bitrate_off = self.query_one("#bitrate", Select).disabled or bitrate == "default"
        cookies_val = self.val("cookies")
        split_cb = self.query_one("#split", Checkbox)
        subs_sel = self.query_one("#subs", Select)
        return Selection(
            audio=self.query_one("#mode", RadioSet).pressed_index == 1,
            codec=None if codec == "none" else codec,
            height=res if isinstance(res, int) else None,
            prefer60=self.query_one("#fps", Checkbox).value and not self.query_one("#fps", Checkbox).disabled,
            aformat=self.val("aformat"),
            bitrate=None if bitrate_off else int(bitrate),
            archive_bundle=self.query_one("#archive", Checkbox).value,
            split_chapters=split_cb.value and not split_cb.disabled,
            subs_mode="off" if subs_sel.disabled else (self.val("subs") or "off"),
            cookies=None if cookies_val in ("", "none") else cookies_val,
            time_range=self.val("range") or None,
        )

    def _build_current_options(self) -> core.DownloadOptions:
        sel = self.selection()
        mode = "audio" if sel.audio else "video"
        playlist = self.query_one("#scope", RadioSet).pressed_index == 1
        pattern = self.val("pattern")
        if pattern == "custom":
            outtmpl = self.val("template") or "%(title)s.%(ext)s"
            if "%(ext)" not in outtmpl:
                outtmpl += ".%(ext)s"
        elif playlist and pattern == "index":
            outtmpl = "%(playlist_index)02d - %(title)s.%(ext)s"
        else:
            outtmpl = "%(title)s.%(ext)s"
        out_dir = os.path.expanduser(self.val("out") or ".")
        outtmpl = os.path.join(out_dir, outtmpl)

        return core.DownloadOptions(
            url=self.val("url"),
            outtmpl=outtmpl,
            playlist=playlist,
            mode=mode,
            audio_format=sel.aformat if sel.audio else None,
            bitrate=str(sel.bitrate) if sel.bitrate else None,
            video_codec=None if sel.audio else sel.codec,
            target_resolution=None if sel.audio else sel.height,
            prefer_60fps=sel.prefer60,
            proxy=self.val("proxy") or None,
            ratelimit=core.parse_rate_limit(self.val("limit")),
            archive_bundle=sel.archive_bundle,
            split_chapters=sel.split_chapters,
            subs_mode=sel.subs_mode,
            cookies_from_browser=sel.cookies,
            time_range=sel.time_range,
        )

    def scan_view(self) -> Optional[kb.ScanView]:
        return kb.ScanView(self.scan.availability, self.scan.heights) if self.scan else None

    def set_res_options(self, heights: list) -> None:
        res = self.query_one("#res", Select)
        current = res.value
        res.set_options([("AUTO", "auto")] + [(f"{h}P", h) for h in heights])
        res.value = current if current in heights else "auto"

    def set_codec_options(self, available_codecs: Optional[set[str]] = None) -> None:
        """Present only codecs supported by the scanned media item (or all codecs when unscanned)."""
        codec_sel = self.query_one("#codec", Select)
        current = codec_sel.value
        if not available_codecs:
            opts = list(CODEC_OPTIONS)
        else:
            opts = [("AUTO", "none")] + [
                (lbl, val) for lbl, val in CODEC_OPTIONS[1:] if val in available_codecs
            ]
            if len(opts) == 1:
                opts = list(CODEC_OPTIONS[:2])  # At least AUTO + H.264
        valid_vals = {v for _, v in opts}
        codec_sel.set_options(opts)
        codec_sel.value = current if current in valid_vals else "none"

    def sync_platform_capabilities(self, detected: Optional[platforms.DetectedMedia] = None) -> None:
        """Enable or disable controls so only options supported by the selected platform/item are active."""
        url_val = self.val("url")
        if detected is None and url_val:
            detected = platforms.detect_platform(url_val)

        split_cb = self.query_one("#split", Checkbox)
        subs_sel = self.query_one("#subs", Select)
        fps_cb = self.query_one("#fps", Checkbox)

        if self.scan:
            # We have real scanned metadata for this exact item
            can_split = self.scan.has_chapters or self.scan.platform in ("youtube", "generic")
            can_subs = self.scan.has_subtitles or self.scan.platform in ("youtube", "facebook", "generic")
            has_60 = any(r.fps >= 50 for r in self.scan.rows)
            split_cb.disabled = not can_split
            if not can_split:
                split_cb.value = False
            subs_sel.disabled = not can_subs
            fps_cb.disabled = bool(self.scan.rows) and not has_60
            if fps_cb.disabled:
                fps_cb.value = False
            if self.scan.availability:
                self.set_codec_options(set(self.scan.availability.keys()))
        elif detected and detected.platform != "invalid":
            spec = detected.spec
            split_cb.disabled = not spec.supports_chapters
            if split_cb.disabled:
                split_cb.value = False
            subs_sel.disabled = not spec.supports_subtitles
            fps_cb.disabled = False
            self.set_codec_options(None)
        else:
            split_cb.disabled = False
            subs_sel.disabled = False
            fps_cb.disabled = False
            self.set_codec_options(None)

    def sync_mode(self) -> None:
        audio = self.query_one("#mode", RadioSet).pressed_index == 1
        self.query_one("#video-row").display = not audio
        self.query_one("#audio-row").display = audio
        self.sync_bitrate()

    def sync_bitrate(self) -> None:
        self.query_one("#bitrate", Select).disabled = self.val("aformat") in ("best", "wav", "flac")

    # ---- the two teaching panels --------------------------------------

    def refresh_card(self) -> None:
        sel, scan = self.selection(), self.scan
        url_val = self.val("url")
        detected = platforms.detect_platform(url_val) if url_val else None
        card = self.query_one("#card", Panel)
        if scan:
            card.border_subtitle = f"SCANNED ({scan.platform.upper()}) · F3 FORMATS"
        elif detected and detected.platform != "invalid":
            card.border_subtitle = f"{detected.label} · F2 TO INSPECT"
        else:
            card.border_subtitle = "UNSCANNED · F2 TO INSPECT"

        if sel.audio:
            audio = scan.audio if scan else None
            s = kb.describe_audio(
                fmt=sel.aformat, bitrate=sel.bitrate, ffmpeg=self.diag.ffmpeg,
                duration=scan.duration if scan else None,
                src_codec=audio.codec if audio else None, src_size=audio.size if audio else None,
            )
        else:
            pick, fell = (core.pick_row(scan.rows, sel.height, sel.codec, sel.prefer60, can_merge=self.diag.ffmpeg)
                          if scan and scan.rows else (None, False))
            s = kb.describe_video(
                codec=sel.codec, height=sel.height, prefer60=sel.prefer60, ffmpeg=self.diag.ffmpeg,
                row=pick, fell_back=fell, offers=scan.availability if scan else None,
                size=core.estimate_size(pick, scan.audio) if pick and scan else None,
            )

        badges = []
        if sel.archive_bundle:
            badges.append("+ARCHIVE")
        if sel.split_chapters:
            badges.append("+SPLIT")
        if sel.subs_mode != "off":
            badges.append(f"+SUBS({sel.subs_mode.upper()})")
        if sel.time_range:
            badges.append(f"CLIP({sel.time_range})")
        if sel.cookies:
            badges.append(f"COOKIE({sel.cookies.upper()})")
        badge_str = ("  [" + " · ".join(badges) + "]") if badges else ""

        t = Text()
        if scan:
            meta = " · ".join(x for x in (scan.channel, kb.fmt_duration(scan.duration), scan.upload_date) if x)
            t.append(trunc(f"{scan.title}  ({meta})", CARD_WIDTH) + "\n", style=f"bold {BRIGHT}")
            if scan.spotify_data and len(scan.spotify_data.items) > 1:
                preview_items = ", ".join(i.title for i in scan.spotify_data.items[:3])
                t.append(trunc(f"  tracks: {preview_items} …", CARD_WIDTH) + "\n", style=DIM)
        elif detected and detected.platform == "openband":
            ui = manifesto._PAYLOAD["ui"]
            t.append(ui["card_line1"], style=f"bold {SIGNAL}")
            t.append(ui["card_line2"], style=f"bold {BRIGHT}")
            t.append(ui["card_line3"], style=AMBER)
            t.append("  " + detected.reason, style=DIM)
            card.update(t)
            return
        elif detected and detected.platform != "invalid":
            if not detected.supported:
                t.append(trunc(f"Unsupported {detected.spec.name} link  ·  see note below", CARD_WIDTH) + "\n", style=f"bold {RED}")
            else:
                t.append(
                    f"{detected.spec.name} {detected.kind.upper()} detected  ·  press F2 to inspect or ENTER to download\n",
                    style=f"bold {BRIGHT}",
                )
        else:
            t.append("No media scanned yet  ·  paste YT, Spotify, IG, X, or FB link & press F2\n", style=DIM)

        t.append("▸ " + s.spec + badge_str + "\n", style=f"bold {SIGNAL}")
        facts = ([f"≈ {kb.fmt_size(s.size)}"] if s.size else ["size: scan first (F2)"]) + [f"plays: {s.plays}"]
        t.append("  " + "  ·  ".join(facts) + "\n", style=AMBER)

        if detected and not detected.supported and detected.reason:
            t.append("! " + trunc(detected.reason, CARD_WIDTH * 2), style=RED)
        elif detected and detected.requires_cookies and not sel.cookies:
            t.append("! " + trunc(detected.reason or detected.spec.auth_hint, CARD_WIDTH * 2), style=ORANGE)
        else:
            if s.notes:
                t.append("  " + s.notes[0] + "\n", style=DIM)
            if s.warns:
                t.append("! " + s.warns[0], style=ORANGE)
        card.update(t)

    def topic_value(self, topic: str):
        if topic == "codec":
            return self.val("codec")
        if topic == "res":
            return self.query_one("#res", Select).value
        if topic in ("fps", "archive", "split"):
            return self.query_one(f"#{topic}", Checkbox).value
        if topic == "mode":
            return "audio" if self.query_one("#mode", RadioSet).pressed_index == 1 else "video"
        if topic == "scope":
            return "playlist" if self.query_one("#scope", RadioSet).pressed_index == 1 else "single"
        if topic in ("aformat", "bitrate", "subs", "cookies", "url"):
            return self.val(topic)
        return None

    def refresh_learn(self, topic: Optional[str] = None) -> None:
        if topic:
            self.topic = topic
        lesson = kb.learn(self.topic, self.topic_value(self.topic), self.scan_view())
        learn_panel = self.query_one("#learn", Panel)
        learn_panel.border_subtitle = f"TOPIC: {self.topic.upper()} · F10 COPY CLI"
        t = Text()
        t.append(lesson.title, style=f"bold {BRIGHT}")
        if lesson.tagline:
            t.append("  ·  " + lesson.tagline, style=f"bold {SIGNAL}")
        t.append("\n")
        if lesson.body:
            t.append(trunc(lesson.body, 148) + "\n", style=AMBER)
        if lesson.ratings:
            t.append(lesson.ratings + "\n", style=BRIGHT)
        elif lesson.facts:
            t.append(lesson.facts + "\n", style=ORANGE)

        # Live CLI Command Equivalent on the bottom line of FIELD GUIDE
        cli_str = core.build_cli_command(self._build_current_options(), can_merge=self.diag.ffmpeg)
        t.append("$ " + trunc(cli_str, 46), style=DIM)
        learn_panel.update(t)

    def refresh_panels(self, topic: Optional[str] = None) -> None:
        self.refresh_card()
        self.refresh_learn(topic)

    # ---- widget events -------------------------------------------------

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        for node in event.widget.ancestors_with_self:
            if node.id in TOPIC_IDS:
                self.refresh_learn(TOPIC_IDS[node.id])
                return

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "mode":
            self.sync_mode()
        self.refresh_panels(event.radio_set.id)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self.refresh_panels(TOPIC_IDS.get(event.checkbox.id or "fps"))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "pattern":
            self.query_one("#template", Input).disabled = event.value != "custom"
        elif event.select.id == "aformat":
            self.sync_bitrate()
        self.refresh_panels(TOPIC_IDS.get(event.select.id or ""))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "url":
            val = event.value.strip()
            if self.scan and val != self.scan.url:
                self.scan = None
                self.set_res_options([])
                self.set_codec_options(None)
            detected = platforms.detect_platform(val) if val else None
            if detected and detected.platform == "spotify":
                mode_rs = self.query_one("#mode", RadioSet)
                for idx, btn in enumerate(mode_rs.query(RadioButton)):
                    btn.value = idx == 1  # switch to AUDIO mode
                self.sync_mode()
                scope_rs = self.query_one("#scope", RadioSet)
                want_pl = detected.kind in ("playlist", "album", "show")
                for idx, btn in enumerate(scope_rs.query(RadioButton)):
                    btn.value = (idx == 1) if want_pl else (idx == 0)
            elif detected and detected.platform == "twitter" and detected.kind == "space":
                mode_rs = self.query_one("#mode", RadioSet)
                for idx, btn in enumerate(mode_rs.query(RadioButton)):
                    btn.value = idx == 1  # X Spaces are audio-only
                self.sync_mode()
            elif detected and detected.platform in ("instagram", "twitter", "facebook"):
                # Default to AUTO/H.264 on social platforms and SINGLE scope unless playlist/carousel
                if not detected.spec.supports_playlists:
                    scope_rs = self.query_one("#scope", RadioSet)
                    for idx, btn in enumerate(scope_rs.query(RadioButton)):
                        btn.value = idx == 0
            elif detected and detected.platform == "youtube" and detected.kind == "playlist":
                scope_rs = self.query_one("#scope", RadioSet)
                for idx, btn in enumerate(scope_rs.query(RadioButton)):
                    btn.value = idx == 1
            self.sync_platform_capabilities(detected)
            self._update_left_col_subtitle()
        self.refresh_panels(TOPIC_IDS.get(event.input.id or ""))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "url":
            self.action_download()

    # ---- worker -> UI handlers ----------------------------------------

    def on_log_line(self, m: LogLine) -> None:
        self.write_log(m.text, m.level)
        if m.toast:
            self.notify(m.text, severity="error" if m.level == "error" else "warning", timeout=6)

    def on_progress_update(self, m: ProgressUpdate) -> None:
        q_suffix = f" [+{len(self.job_queue)}q]" if self.job_queue else ""
        self.set_gauge(m.fraction, (m.label or "running") + q_suffix)

    def on_scan_done(self, m: ScanDone) -> None:
        self.scan = m.scan
        self.set_res_options(m.scan.heights)
        self.sync_platform_capabilities()
        plat_spec = platforms.PLATFORMS.get(m.scan.platform, platforms.PLATFORMS["generic"])
        self.write_log(f"[{plat_spec.badge}] {m.scan.title}", "ok")
        if m.scan.channel:
            self.write_log(f"creator: {m.scan.channel}   ·   source: {m.scan.webpage_url or m.scan.url}", "note")
        if m.scan.spotify_data:
            sp = m.scan.spotify_data
            count = len(sp.items)
            kind_lbl = "podcast episode" if sp.kind == "episode" else ("podcast show" if sp.kind == "show" else sp.kind)
            self.write_log(f"Spotify {kind_lbl}: {sp.creator} · {count} item{'s' if count != 1 else ''} ready", "note")
            for item in sp.items[:5]:
                dur_s = f" ({kb.fmt_duration(item.duration)})" if item.duration else ""
                self.write_log(f"  {item.index:02d}. {item.artist} - {item.title}{dur_s}", "info")
            if count > 5:
                self.write_log(f"  … and {count - 5} more item(s)", "note")
        elif m.scan.rows:
            avail = "  ·  ".join(f"{kb.codec_label(k)} ≤{h}p" for k, h in sorted(m.scan.availability.items()))
            self.write_log(f"offers: {avail}   (F3 lists every format)", "note")
        elif m.scan.audio:
            self.write_log(f"audio stream ready: {m.scan.audio.codec} ({m.scan.audio.abr or '?'} kbps)", "note")
        else:
            self.write_log("no video formats found — try again, or press F1 to check setup", "warn")
        self.refresh_panels()

    def on_folder_known(self, m: FolderKnown) -> None:
        self.last_dir = m.path

    def on_update_available(self, m: UpdateAvailable) -> None:
        self.update_version = m.version
        self.query_one("#env", Static).update(self.env_text())
        self.write_log(f"yt-dlp {m.version} is available — press F9 to update", "warn")

    def on_job_done(self, m: JobDone) -> None:
        if self.job_queue and not self.cancel_event.is_set():
            next_job = self.job_queue.popleft()
            self._update_left_col_subtitle()
            self.set_gauge(0.0, "starting queued job")
            self.write_log(f"starting queued job: {next_job.options.url}", "note")
            self.download_worker(next_job)
        else:
            self.busy = False
            self._update_left_col_subtitle()

    # ---- actions -------------------------------------------------------

    def _apply_preset(self, key: str) -> None:
        preset = self.presets.get(key)
        if not preset:
            return
        self.active_preset_name = preset.name
        mode_rs = self.query_one("#mode", RadioSet)
        want_audio = preset.mode == "audio"
        for idx, btn in enumerate(mode_rs.query(RadioButton)):
            btn.value = (idx == 1) if want_audio else (idx == 0)
        self.sync_mode()
        self.set_codec_options(None)
        self.query_one("#codec", Select).value = preset.codec
        res_sel = self.query_one("#res", Select)
        if preset.res == "auto":
            res_sel.value = "auto"
        else:
            heights = self.scan.heights if self.scan else [2160, 1440, 1080, 720, 480]
            if preset.res not in heights:
                heights = sorted(set(heights + [int(preset.res)]), reverse=True)
            self.set_res_options(heights)
            res_sel.value = int(preset.res)
        self.query_one("#fps", Checkbox).value = preset.fps60
        self.query_one("#aformat", Select).value = preset.aformat
        self.sync_bitrate()
        self.query_one("#bitrate", Select).value = preset.bitrate
        self.query_one("#archive", Checkbox).value = preset.archive_bundle
        if not self.query_one("#subs", Select).disabled:
            self.query_one("#subs", Select).value = preset.subs_mode
        self._update_left_col_subtitle()
        self.refresh_panels()
        self.write_log(f"preset [{key}]: {preset.name}", "ok")

    def action_preset_1(self) -> None:
        self._apply_preset("1")

    def action_preset_2(self) -> None:
        self._apply_preset("2")

    def action_preset_3(self) -> None:
        self._apply_preset("3")

    def action_preset_4(self) -> None:
        self._apply_preset("4")

    def action_copy_cli(self) -> None:
        cmd = core.build_cli_command(self._build_current_options(), can_merge=self.diag.ffmpeg)
        copied = core.copy_to_clipboard(cmd)
        self.write_log(f"CLI: {cmd}", "info")
        if copied:
            self.notify("yt-dlp CLI command copied to clipboard", timeout=3)
        else:
            self.notify("CLI command printed to Activity Log", timeout=3)

    def _enqueue_url_list(self, urls: list[str]) -> None:
        valid = [u for u in urls if platforms.detect_platform(u).supported]
        if not valid:
            self.warn("no valid supported media URLs found in batch")
            return
        url_input = self.query_one("#url", Input)
        first = valid[0]
        rest = valid[1:]
        url_input.value = first
        self.action_download()
        for u in rest:
            det = platforms.detect_platform(u)
            base_opts = self._build_current_options()
            # Adapt mode to audio automatically for Spotify or X Spaces in a mixed batch
            item_mode = "audio" if (det.platform == "spotify" or (det.platform == "twitter" and det.kind == "space")) else base_opts.mode
            item_aformat = (base_opts.audio_format or "mp3") if item_mode == "audio" else None
            job_opts = core.DownloadOptions(
                url=u,
                outtmpl=base_opts.outtmpl,
                playlist=base_opts.playlist or (det.kind in ("playlist", "album", "show")),
                mode=item_mode,
                audio_format=item_aformat,
                bitrate=base_opts.bitrate,
                video_codec=None if item_mode == "audio" else base_opts.video_codec,
                target_resolution=None if item_mode == "audio" else base_opts.target_resolution,
                prefer_60fps=base_opts.prefer_60fps,
                proxy=base_opts.proxy,
                ratelimit=base_opts.ratelimit,
                archive_bundle=base_opts.archive_bundle,
                split_chapters=base_opts.split_chapters and det.spec.supports_chapters,
                subs_mode=base_opts.subs_mode if det.spec.supports_subtitles else "off",
                cookies_from_browser=base_opts.cookies_from_browser,
                time_range=base_opts.time_range,
            )
            spec_hint = (
                f"AUDIO · {(job_opts.audio_format or 'best').upper()}"
                if item_mode == "audio"
                else f"VIDEO · {kb.codec_label(job_opts.video_codec)} · {job_opts.target_resolution or 'AUTO'}p"
            )
            self.job_queue.append(
                QueuedJob(
                    options=job_opts,
                    availability=None,
                    title_hint=u,
                    channel_hint=det.spec.name,
                    spec_hint=spec_hint,
                )
            )
        self._update_left_col_subtitle()
        if rest:
            self.write_log(f"batch import: started #1 and queued {len(rest)} additional URL(s)", "ok")
            self.notify(f"Batch imported {len(valid)} URLs into queue", timeout=4)

    def action_paste_scan(self) -> None:
        clip = core.read_clipboard()
        if not clip:
            self.warn("clipboard is empty or unavailable")
            return
        urls = core.parse_batch_urls(clip)
        if len(urls) > 1:
            self.push_screen(BatchImportScreen(initial_text=clip), lambda res: self._enqueue_url_list(res) if res else None)
            return
        url_input = self.query_one("#url", Input)
        url_input.value = (urls[0] if urls else clip.splitlines()[0]).strip()
        url_input.focus()
        self.action_scan()

    def action_batch_import(self) -> None:
        clip = core.read_clipboard()
        urls = core.parse_batch_urls(clip)
        seed = clip if len(urls) > 1 else ""
        self.push_screen(BatchImportScreen(initial_text=seed), lambda res: self._enqueue_url_list(res) if res else None)

    def action_catalog(self) -> None:
        def _on_catalog_dismiss(chosen_url: Optional[str]) -> None:
            if chosen_url:
                url_in = self.query_one("#url", Input)
                url_in.value = chosen_url
                url_in.focus()
                self.write_log(f"loaded from catalog: {chosen_url}", "note")

        self.push_screen(CatalogScreen(), _on_catalog_dismiss)

    def action_cycle_art(self) -> None:
        banner = self.query_one("#right-col", ManifestoBanner)
        comp = banner.next_scene()
        self.scene_index = banner.scene_index
        self.quote_index = banner.quote_index
        self._update_masthead_slogan()
        manifesto.save_state({
            "scene_index": self.scene_index,
            "quote_index": self.quote_index,
            "sessions": self.session_number,
        })
        self.write_log(f'[{comp.artwork.title}] "{comp.quote}"', "note")

    def _open_manifesto_screen(self, start_with_letter: bool = False) -> None:
        def _sync_back(result: Optional[tuple[int, int]]) -> None:
            if result is not None:
                s_idx, q_idx = result
                self.scene_index = s_idx
                self.quote_index = q_idx
                banner = self.query_one("#right-col", ManifestoBanner)
                banner.scene_index = s_idx
                banner.quote_index = q_idx
                self._update_masthead_slogan()
                manifesto.save_state({
                    "scene_index": self.scene_index,
                    "quote_index": self.quote_index,
                    "sessions": self.session_number,
                })
            self.query_one("#url", Input).focus()

        self.push_screen(
            ManifestoScreen(
                self.scene_index,
                self.quote_index,
                greeting=self.greeting,
                start_with_letter=start_with_letter,
            ),
            _sync_back,
        )

    def _trigger_manifesto_easter_egg(self, raw_trigger: str) -> None:
        """Demodulate Carrier 00 telemetry when a matching signature is entered in the URL bar."""
        ui = manifesto._PAYLOAD["ui"]
        out_dir = os.path.expanduser(self.val("out") or ".")
        saved_path = None
        try:
            os.makedirs(out_dir, exist_ok=True)
            dest = os.path.join(out_dir, ui["filename"])
            with open(dest, "w", encoding="utf-8") as fp:
                fp.write(manifesto.MANIFESTO_LETTER + "\n")
            saved_path = os.path.abspath(dest)
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            core.append_catalog(
                core.CatalogEntry(
                    title=ui["cat_title"],
                    channel=ui["cat_channel"],
                    url=ui["cat_url"],
                    spec=ui["cat_spec"],
                    size=os.path.getsize(saved_path),
                    path=saved_path,
                    archived_at=now_str,
                )
            )
        except Exception:  # noqa: BLE001
            pass

        self.set_gauge(1.0, ui["gauge_done"])
        self.write_log(ui["log_unlock"], "ok")
        if saved_path:
            self.last_dir = os.path.dirname(saved_path)
            self.write_log(f"saved local copy: {saved_path}   (recorded in F4 Commons Catalog)", "note")
        self.notify(ui["toast"], timeout=5)
        self._open_manifesto_screen(start_with_letter=True)

    def action_manifesto_modal(self) -> None:
        self._open_manifesto_screen(start_with_letter=True)

    def action_scan(self) -> None:
        if self.busy:
            self.warn("wait for the current job to finish before scanning")
            return
        url = self.val("url")
        if not url:
            self.warn("paste a link first")
            return
        detected = platforms.detect_platform(url)
        if detected.platform == "openband":
            self._trigger_manifesto_easter_egg(url)
            return
        if not detected.supported:
            self.warn(detected.reason or "Unsupported media URL.")
            return
        sel = self.selection()
        if detected.requires_cookies and not sel.cookies and not os.environ.get("OPENBAND_COOKIES_FILE"):
            self.write_log(f"note: {detected.reason or detected.spec.auth_hint}", "warn")
        self.busy = True
        self.set_gauge(0.0, f"scanning {detected.spec.badge.lower()}…")
        self.write_log(f"scanning [{detected.label}] …", "note")
        self.scan_worker(
            url,
            self.query_one("#scope", RadioSet).pressed_index == 1,
            self.val("proxy") or None,
            sel.cookies,
        )

    def action_formats(self) -> None:
        if not self.scan or not self.scan.rows:
            self.warn("scan first (F2) to list the real formats")
            return
        sel = self.selection()
        if sel.audio:
            self.warn("the format list is for video — switch MODE to VIDEO")
            return
        current, _ = core.pick_row(self.scan.rows, sel.height, sel.codec, sel.prefer60, can_merge=self.diag.ffmpeg)
        self.push_screen(FormatScreen(self.scan, current), self.apply_row)

    def apply_row(self, chosen: Optional[core.FormatRow]) -> None:
        if chosen is None:
            return
        self.query_one("#codec", Select).value = chosen.codec if chosen.codec in kb.CODEC_KEYS else "none"
        self.query_one("#res", Select).value = chosen.height
        self.query_one("#fps", Checkbox).value = chosen.fps >= 50
        self.refresh_panels("codec")
        self.write_log(f"selected {chosen.height}p · {kb.codec_label(chosen.codec)} · {chosen.fps}fps", "note")

    def action_download(self) -> None:
        url = self.val("url")
        if not url:
            self.warn("paste a link first")
            return
        detected = platforms.detect_platform(url)
        if detected.platform == "openband":
            self._trigger_manifesto_easter_egg(url)
            return
        if not detected.supported:
            self.warn(detected.reason or "Unsupported media URL.")
            return
        sel = self.selection()
        if detected.requires_cookies and not sel.cookies and not os.environ.get("OPENBAND_COOKIES_FILE"):
            self.write_log(f"note: {detected.reason or detected.spec.auth_hint}", "warn")

        audio_format = sel.aformat if sel.audio else None
        if audio_format and audio_format != "best" and not self.diag.ffmpeg:
            self.warn("ffmpeg is required for audio conversion — pick BEST, or press F1 for help")
            return

        if sel.time_range and core.parse_time_range(sel.time_range) is None:
            self.warn(f"invalid time range {sel.time_range!r} — use MM:SS-MM:SS (e.g. 01:20-04:15)")
            return

        limit_text = self.val("limit")
        if limit_text and core.parse_rate_limit(limit_text) is None:
            self.warn(f"ignoring invalid speed limit: {limit_text!r}")

        options = self._build_current_options()
        spec_hint = (
            f"AUDIO · {(options.audio_format or 'best').upper()}"
            if options.mode == "audio"
            else f"VIDEO · {kb.codec_label(options.video_codec)} · {options.target_resolution or 'AUTO'}p"
        )
        job = QueuedJob(
            options=options,
            availability=self.scan.availability if (self.scan and self.scan.url == url) else None,
            title_hint=self.scan.title if (self.scan and self.scan.url == url) else url,
            channel_hint=self.scan.channel if (self.scan and self.scan.url == url) else detected.spec.name,
            spec_hint=spec_hint,
        )

        # Non-blocking Download Queue: if busy, enqueue and continue
        if self.busy:
            self.job_queue.append(job)
            self._update_left_col_subtitle()
            self.write_log(f"queued (#{len(self.job_queue)}) [{detected.label}]: {job.title_hint}", "info")
            self.notify(f"Added to queue ({len(self.job_queue)} pending)", timeout=3)
            return

        self.cancel_event.clear()
        self.busy = True
        self._update_left_col_subtitle()
        self.set_gauge(0.0, f"starting {detected.spec.badge.lower()}")
        self.write_log(f"starting [{detected.label}] …", "note")
        self.download_worker(job)

    def action_cancel(self) -> None:
        if self.job_queue:
            cleared = len(self.job_queue)
            self.job_queue.clear()
            self._update_left_col_subtitle()
            self.write_log(f"cleared {cleared} queued job(s)", "warn")
        if self.busy:
            self.cancel_event.set()
            self.write_log("cancelling active job …", "note")

    def action_open_folder(self) -> None:
        path = os.path.expanduser(self.last_dir or self.val("out") or ".")
        if os.path.isdir(path):
            core.open_folder(path)
        else:
            self.warn("output folder not found")

    def action_more(self) -> None:
        more = self.query_one("#more")
        more.display = not more.display
        self.query_one("#morehint", Static).update(
            "▾ F7  hide advanced options   ·   Alt+1..4 presets"
            if more.display
            else "▸ F7  subs · cookies · range · limit · proxy   ·   Alt+1..4 presets"
        )

    def action_setup(self) -> None:
        self.diag = core.diagnose()
        self.query_one("#env", Static).update(self.env_text())
        self.refresh_card()
        for text, level in core.setup_lines(self.diag):
            self.write_log(text, level)

    def action_update(self) -> None:
        if self.busy:
            self.warn("wait for the current job to finish")
            return
        self.busy = True
        self.write_log("updating yt-dlp …", "note")
        self.update_worker()

    def action_quit(self) -> None:
        self.job_queue.clear()
        self.cancel_event.set()
        self.exit()

    # ---- workers (threads) --------------------------------------------

    def _error_sink(self, post, seen: set):
        def sink(text: str, level: str) -> None:
            if level != "error":
                post(LogLine(text, level))
                return
            f = core.friendly_error(text)
            if f.headline in seen:
                return
            seen.add(f.headline)
            post(LogLine(f.headline, "error", toast=True))
            if f.hint:
                post(LogLine("→ " + f.hint, "note"))
        return sink

    @work(thread=True, exclusive=True, group="scan")
    def scan_worker(
        self,
        url: str,
        playlist: bool,
        proxy: Optional[str],
        cookies: Optional[str],
    ) -> None:
        try:
            scan_data = core.scan(url, playlist, proxy, cookies)
            self.post_message(ScanDone(scan_data))
            self.post_message(ProgressUpdate(1.0, "scanned"))
        except Exception as e:  # noqa: BLE001
            f = core.friendly_error(str(e))
            self.post_message(LogLine("scan failed: " + f.headline, "error", toast=True))
            if f.hint:
                self.post_message(LogLine("→ " + f.hint, "note"))
            self.post_message(ProgressUpdate(0.0, "scan failed"))
        finally:
            self.post_message(JobDone())

    @work(thread=True, group="download")
    def download_worker(self, job: QueuedJob) -> None:
        o = job.options
        availability = job.availability
        post = self.post_message
        files: list = []
        got: dict = {}
        titles: dict = {}
        channels: dict = {}
        source_urls: dict = {}
        seen: set = set()
        detected = platforms.detect_platform(o.url)
        try:
            total = 0
            if o.playlist and not spotify.is_spotify_url(o.url):
                try:
                    total = core.count_playlist_entries(o.url, o.proxy, o.cookies_from_browser)
                except Exception as e:  # noqa: BLE001
                    post(LogLine(f"could not count playlist items: {core.clean(e)}", "warn"))

            def _on_item(item: int, info: dict) -> None:
                core._check_drm(info)
                got[item] = core.summarize_got(info)
                if info.get("title"):
                    titles[item] = str(info["title"])
                creator = platforms.extract_creator_handle(info, detected)
                if creator:
                    channels[item] = creator
                if info.get("webpage_url"):
                    source_urls[item] = str(info["webpage_url"])

            hook = core.make_progress_hook(
                total, lambda frac, label: post(ProgressUpdate(frac, label)), self.cancel_event.is_set,
                on_item=_on_item,
            )
            ydl_opts = core.build_ydl_opts(
                o, hook, core.YdlLogger(self._error_sink(post, seen)),
                on_file=files.append, can_merge=self.diag.ffmpeg,
            )
            post(LogLine(f"platform: {detected.label}  ·  format: {ydl_opts['format']}", "note"))

            if spotify.is_spotify_url(o.url):
                post(LogLine("resolving Spotify metadata …", "note"))
                sp_resolved = spotify.resolve_spotify(o.url, proxy=o.proxy)
                post(LogLine(f"Spotify {sp_resolved.kind}: {sp_resolved.title} ({len(sp_resolved.items)} item(s))", "ok"))
                out_dir = os.path.dirname(os.path.abspath(o.outtmpl)) or "."
                numbering = "%(playlist_index)" in o.outtmpl or sp_resolved.kind in ("album", "playlist", "show")
                sp_files = spotify.download_spotify(
                    sp_resolved,
                    out_dir=out_dir,
                    audio_format=o.audio_format or "mp3",
                    bitrate=o.bitrate or "192",
                    playlist_numbering=numbering,
                    proxy=o.proxy,
                    ratelimit=o.ratelimit,
                    cookies_from_browser=o.cookies_from_browser,
                    can_merge=self.diag.ffmpeg,
                    progress_cb=lambda frac, label: post(ProgressUpdate(frac, label)),
                    log_cb=lambda msg, lvl: post(LogLine(msg, lvl)),
                    is_cancelled=self.cancel_event.is_set,
                )
                files.extend(sp_files)
                failed = 0 if sp_files else 1
                titles[1] = sp_resolved.title
                channels[1] = sp_resolved.creator
                source_urls[1] = sp_resolved.url
            else:
                if yt_dlp is None:
                    raise RuntimeError("yt-dlp is not installed.")
                target_url = detected.canonical_url if detected.canonical_url else o.url
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    failed = ydl.download([target_url])

            paths = [p for p in files if os.path.exists(p)]
            size = sum(os.path.getsize(p) for p in paths)
            if failed or not paths:
                if not paths and not failed:
                    post(LogLine("no media file was produced — check if the post contains video/audio or requires cookies (F7)", "warn"))
                else:
                    post(LogLine("finished with errors", "warn"))
                post(ProgressUpdate(1.0 if paths else 0.0, "done (errors)" if paths else "failed"))
            else:
                post(LogLine(f"archived · {len(paths)} file{'s' if len(paths) != 1 else ''} · {kb.fmt_size(size)} · user-owned copy", "ok"))
                post(ProgressUpdate(1.0, "done"))

            folder = os.path.dirname(os.path.abspath(paths[0])) if paths else os.path.dirname(os.path.abspath(o.outtmpl))
            if paths:
                post(FolderKnown(folder))
                post(LogLine(f"saved to {folder}   (F6 opens folder · F4 Commons Catalog)", "note"))

            # Clean transcript generation if requested
            if o.subs_mode == "transcript" and os.path.isdir(folder):
                txt_files = core.write_clean_transcripts(folder)
                if txt_files:
                    post(LogLine(f"clean transcript saved: {os.path.basename(txt_files[0])}", "ok"))

            # Record in Commons Catalog (~/.openband_catalog.json) and write .nfo provenance sidecar if ARCHIVE is on
            if paths:
                first_got = got.get(1)
                actual_spec = kb.describe_got(first_got) if first_got else job.spec_hint
                if detected.platform not in ("invalid", "generic"):
                    actual_spec = f"{detected.spec.badge} · {actual_spec}"
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                final_title = titles.get(1) or job.title_hint
                final_creator = channels.get(1) or job.channel_hint
                final_url = source_urls.get(1) or o.url
                core.append_catalog(
                    core.CatalogEntry(
                        title=final_title,
                        channel=final_creator,
                        url=final_url,
                        spec=actual_spec,
                        size=size,
                        path=os.path.abspath(paths[0]),
                        archived_at=now_str,
                    )
                )
                if o.archive_bundle:
                    nfo_file = core.write_provenance_nfo(
                        os.path.abspath(paths[0]),
                        title=final_title,
                        creator=final_creator,
                        source_url=final_url,
                        platform=detected.platform,
                        spec=actual_spec,
                        archived_at=now_str,
                    )
                    if nfo_file:
                        post(LogLine(f"provenance sidecar saved: {nfo_file.name}", "note"))

            if o.mode == "video":
                for text, level in kb.report_video(
                    asked_codec=o.video_codec, asked_height=o.target_resolution, asked_prefer60=o.prefer_60fps,
                    gots=[got[k] for k in sorted(got)], availability=availability,
                ):
                    post(LogLine(text, level))
            elif paths:
                exts = Counter(os.path.splitext(p)[1].lstrip(".").upper() for p in paths)
                asked = (o.audio_format or "best").upper() + (f" · {o.bitrate} kbps" if o.bitrate else "")
                post(LogLine(f"asked: {asked}", "note"))
                post(LogLine("got:   " + "   ".join(f"{n}× {e}" if n > 1 else e for e, n in exts.most_common()), "info"))
        except Exception as e:  # noqa: BLE001
            if self.cancel_event.is_set() or isinstance(e, core.DownloadCancelled):
                post(LogLine("cancelled", "warn"))
                post(ProgressUpdate(0.0, "cancelled"))
            else:
                f = core.friendly_error(str(e))
                if f.headline not in seen:
                    post(LogLine(f.headline, "error", toast=True))
                    if f.hint:
                        post(LogLine("→ " + f.hint, "note"))
                post(ProgressUpdate(0.0, "failed"))
        finally:
            post(JobDone())

    @work(thread=True, exclusive=True, group="update-check")
    def check_update_worker(self) -> None:
        latest = core.latest_ytdlp_version()
        if latest and core.is_newer(latest, core.YTDLP_VERSION):
            self.post_message(UpdateAvailable(latest))

    @work(thread=True, group="update")
    def update_worker(self) -> None:
        post = self.post_message
        try:
            rc = core.update_ytdlp(lambda line: post(LogLine(line, "note")))
            if rc == 0:
                post(LogLine("yt-dlp updated — restart OpenBand to use the new version", "ok", toast=False))
            else:
                post(LogLine("update failed — try:  python -m pip install -U yt-dlp", "error"))
        except Exception as e:  # noqa: BLE001
            post(LogLine(f"update failed: {core.clean(e)}", "error"))
        finally:
            post(JobDone())


OpenBandApp = YtdlApp


def parse_cli_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="openband",
        description="OpenBand — A Movement for Free Media. Multi-platform terminal front-end for YouTube, Spotify, Instagram, X (Twitter), and Facebook.",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Optional media URL(s) to enqueue immediately on launch.",
    )
    parser.add_argument(
        "-b", "--batch-file",
        dest="batch_file",
        default=None,
        help="Path to a text/markdown file of URLs (one per line) to enqueue on launch.",
    )
    parser.add_argument(
        "-p", "--preset",
        dest="preset",
        choices=["1", "2", "3", "4"],
        default=None,
        help="Apply a built-in preset on launch (1=MP4, 2=Archive Bundle, 3=MP3 320k, 4=FLAC).",
    )
    parser.add_argument(
        "--export-catalog",
        dest="export_catalog",
        action="store_true",
        help="Export the local Commons Catalog to ~/openband_catalog.{m3u8,md,csv} and exit.",
    )
    parser.add_argument(
        "--fast", "--no-splash",
        dest="fast",
        action="store_true",
        help="Skip the opening manifesto sequence and jump straight to the operational desk.",
    )
    parser.add_argument(
        "--scene",
        dest="scene",
        default=None,
        help="Start with a specific artwork plate key or index (e.g. skyline, bridge, cabin, archive, tower, doorway).",
    )
    parser.add_argument(
        "--manifesto",
        dest="print_manifesto",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_cli_args(argv)
    if args.print_manifesto:
        print(manifesto.render_manifesto_letter(width=72).plain)
        print(manifesto.render_exit_banner(session_number=1, archived_count=len(core.load_catalog())))
        return

    if args.export_catalog:
        entries = core.load_catalog()
        m3u_p = core.export_catalog_m3u8(entries)
        md_p = core.export_catalog_markdown(entries)
        csv_p = core.export_catalog_csv(entries)
        print(f"Exported {len(entries)} catalog item(s):")
        print(f"  • M3U8 Playlist : {m3u_p}")
        print(f"  • Markdown Index: {md_p}")
        print(f"  • CSV Ledger    : {csv_p}")
        return

    initial_urls: list[str] = []
    if args.batch_file:
        initial_urls.extend(core.load_batch_file(args.batch_file))
    if args.urls:
        initial_urls.extend(core.parse_batch_urls("\n".join(args.urls)))

    start_scene = manifesto.initial_scene_index(args.scene) if args.scene is not None else None
    show_splash = False if (args.fast or initial_urls) else None
    app = OpenBandApp(
        start_scene=start_scene,
        show_splash=show_splash,
        initial_urls=initial_urls,
        initial_preset=args.preset,
    )
    app.run()
    try:
        archived_total = len(core.load_catalog())
        print(manifesto.render_exit_banner(session_number=app.session_number, archived_count=archived_total))
    except Exception:  # noqa: BLE001
        pass
