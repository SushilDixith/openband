"""screens — modal screens for OpenBand (Formats, Cinematic Opening, Commons Catalog,
Batch URL Importer, and Offline Transcript Reader).
"""
import os
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static, TextArea

from . import core, knowledge as kb, manifesto, platforms
from .theme import AMBER, BRIGHT, DIM, ORANGE, RED, SIGNAL


class FormatScreen(ModalScreen):
    """Every real format of the scanned video. ENTER applies the highlighted one; ESC closes."""

    BINDINGS = [("escape", "close", "CLOSE")]

    def __init__(self, scan: core.ScanData, current: Optional[core.FormatRow] = None):
        super().__init__()
        self.scan = scan
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="fmt-box"):
            yield Static(
                Text.assemble(("((●)) STREAM SPECTRUM ▸ ", SIGNAL), (self.scan.title[:66], f"bold {BRIGHT}")),
                id="fmt-title",
            )
            yield DataTable(id="fmt-table", cursor_type="row", zebra_stripes=False, cell_padding=2)
            yield Static(id="fmt-learn")
            yield Static(
                "ENTER lock selected stream   ·   ESC return   ·   ★ active selection   ·   sizes include audio",
                id="fmt-keys",
            )

    def on_mount(self) -> None:
        box = self.query_one("#fmt-box", Vertical)
        box.border_title = "((●)) OPENBAND · FORMAT & CODEC INSPECTOR"
        box.border_subtitle = "PORTABILITY BY DEFAULT"
        table = self.query_one("#fmt-table", DataTable)
        table.add_columns("PICK", "RES", "FPS", "CODEC", "BOX", "≈ SIZE", "PORTABILITY")
        for i, r in enumerate(self.scan.rows):
            info = kb.CODECS[kb.codec_key(r.codec)]
            mark = "★" if r == self.current else " "
            table.add_row(
                Text(mark, style=f"bold {SIGNAL}"),
                f"{r.height}p", str(r.fps), kb.codec_label(r.codec), kb.container_for(r.codec),
                Text(kb.fmt_size(core.estimate_size(r, self.scan.audio)), justify="right"),
                info.short, key=str(i),
            )
        if self.current in self.scan.rows:
            table.move_cursor(row=self.scan.rows.index(self.current))
        table.focus()
        self.show_lesson(table.cursor_row)

    def show_lesson(self, index: int) -> None:
        if not 0 <= index < len(self.scan.rows):
            return
        r = self.scan.rows[index]
        codec = kb.CODECS[kb.codec_key(r.codec)]
        label, use = kb.res_band(r.height)[1:]
        t = Text()
        t.append(f"{r.height}p {label} · {codec.name}" + (" · 60fps" if r.fps >= 50 else "") + "\n", style=f"bold {BRIGHT}")
        t.append(use + "\n", style=AMBER)
        t.append(codec.tagline + "\n", style=AMBER)
        ratings = kb.ratings_line(r.codec)
        if ratings:
            t.append(ratings + "   ·   ", style=SIGNAL)
        t.append(f"Plays on: {codec.plays_on}.  Container: {kb.container_for(r.codec)}.", style=DIM)
        self.query_one("#fmt-learn", Static).update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.show_lesson(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self.scan.rows):
            self.dismiss(self.scan.rows[event.cursor_row])

    def action_close(self) -> None:
        self.dismiss(None)


class ManifestoScreen(ModalScreen):
    """Cinematic opening sequence (plates) & carrier transmission stage."""

    BINDINGS = [
        ("enter", "close", "ENTER OPENBAND"),
        ("escape", "close", "SKIP / CLOSE"),
        ("space", "close", "ENTER OPENBAND"),
        ("s", "save_letter", "SAVE"),
        ("f8", "next_scene", "NEXT PLATE"),
        ("right", "next_scene", "NEXT PLATE"),
        ("left", "prev_scene", "PREV PLATE"),
    ]

    def __init__(
        self,
        initial_index: int = 0,
        initial_quote: Optional[int] = None,
        greeting: Optional[str] = None,
        animate: bool = True,
        start_with_letter: bool = False,
    ):
        super().__init__()
        self.index = initial_index
        self.quote_index = initial_index if initial_quote is None else initial_quote
        self.greeting = greeting or manifesto.build_greeting()
        self.animate = animate and not start_with_letter
        self.step = 1 if self.animate else 4
        self.show_tenets = start_with_letter
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="manifesto-box"):
            yield Static(id="manifesto-header")
            with VerticalScroll(id="manifesto-scroll"):
                yield Static(id="manifesto-stage")
            yield Static(id="manifesto-concept")
            yield Static(
                manifesto._PAYLOAD["ui"]["reader_keys"]
                if self.show_tenets
                else "▸ ENTER / SPACE / ESC open desk   ·   ← / → / F8 cycle plates",
                id="manifesto-keys",
            )

    def on_mount(self) -> None:
        self.query_one("#manifesto-scroll", VerticalScroll).focus()
        self._refresh_view()
        if self.animate and self.step < 4:
            self._timer = self.set_interval(0.16, self._advance_opening)

    def _advance_opening(self) -> None:
        if self.step < 4:
            self.step += 1
            self._refresh_view()
        elif self._timer is not None:
            self._timer.stop()

    def _refresh_view(self) -> None:
        total = len(manifesto.ARTWORKS)
        comp = manifesto.get_composition(self.index, self.quote_index)
        box = self.query_one("#manifesto-box", Vertical)
        scroll = self.query_one("#manifesto-scroll", VerticalScroll)
        box.border_title = "((●)) OPENBAND  ·  A MOVEMENT FOR FREE MEDIA"
        box.border_subtitle = (
            f"{manifesto.MANIFESTO_TITLE} · {manifesto.MANIFESTO_SUBTITLE.upper()}"
            if self.show_tenets
            else f"PLATE {(self.index % total) + 1:02d}/{total:02d} · {comp.artwork.title}"
        )

        hdr = Text.assemble(("▸ ", SIGNAL), (self.greeting, f"bold {BRIGHT}"))
        self.query_one("#manifesto-header", Static).update(hdr)

        if self.show_tenets:
            ui = manifesto._PAYLOAD["ui"]
            letter_text = manifesto.render_manifesto_letter(width=68)
            self.query_one("#manifesto-stage", Static).update(letter_text)
            self.query_one("#manifesto-concept", Static).update(Text(ui["reader_concept"], style=SIGNAL))
            self.query_one("#manifesto-keys", Static).update(ui["reader_keys"])
            scroll.scroll_home(animate=False)
        else:
            stage_text = manifesto.render_opening_frame(comp, step=self.step, width=68)
            self.query_one("#manifesto-stage", Static).update(stage_text)
            concept_line = Text.assemble(
                (f"[{comp.artwork.title}] ", f"bold {SIGNAL}"),
                (comp.artwork.concept, DIM),
            )
            self.query_one("#manifesto-concept", Static).update(concept_line)
            scroll.scroll_home(animate=False)

    def action_save_letter(self) -> None:
        if not self.show_tenets:
            return
        try:
            dest = Path.cwd() / manifesto._PAYLOAD["ui"]["filename"]
            dest.write_text(manifesto.MANIFESTO_LETTER + "\n", encoding="utf-8")
            self.query_one("#manifesto-concept", Static).update(
                Text(f"✓ Saved archival transmission to {dest}", style=f"bold {SIGNAL}")
            )
            self.app.notify(f"Saved {dest.name}", timeout=4)
        except Exception as e:  # noqa: BLE001
            self.app.notify(f"Could not save file: {e}", severity="error", timeout=4)

    def action_next_scene(self) -> None:
        self.step = 4
        self.show_tenets = False
        self.index = (self.index + 1) % len(manifesto.ARTWORKS)
        self.quote_index = (self.quote_index + 1) % len(manifesto.QUOTES)
        self._refresh_view()

    def action_prev_scene(self) -> None:
        self.step = 4
        self.show_tenets = False
        self.index = (self.index - 1) % len(manifesto.ARTWORKS)
        self.quote_index = (self.quote_index - 1) % len(manifesto.QUOTES)
        self._refresh_view()

    def action_close(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.dismiss((self.index, self.quote_index))


class TranscriptScreen(ModalScreen):
    """Offline Transcript Reader — searchable plain-text viewer for harvested `.transcript.txt` files."""

    BINDINGS = [
        ("escape", "close", "CLOSE"),
        ("slash", "focus_search", "SEARCH"),
    ]

    def __init__(self, title: str, transcript_path: Path):
        super().__init__()
        self.media_title = title
        self.transcript_path = transcript_path
        try:
            self.raw_text = transcript_path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            self.raw_text = ""

    def compose(self) -> ComposeResult:
        lines_count = len(self.raw_text.splitlines())
        words_count = len(self.raw_text.split())
        with Vertical(id="tx-box"):
            yield Static(
                Text.assemble(
                    ("((●)) OFFLINE TRANSCRIPT READER ▸ ", SIGNAL),
                    (self.media_title[:54], f"bold {BRIGHT}"),
                ),
                id="tx-title",
            )
            yield Input(placeholder="search inside transcript… (press / to focus, ENTER to jump)", id="tx-search")
            with VerticalScroll(id="tx-scroll"):
                yield Static(id="tx-body")
            yield Static(
                f"FILE: {self.transcript_path.name}   ·   {lines_count} lines · {words_count} words",
                id="tx-meta",
            )
            yield Static("↑ / ↓ / PgUp / PgDn scroll   ·   / filter & highlight   ·   ESC return to catalog", id="tx-keys")

    def on_mount(self) -> None:
        box = self.query_one("#tx-box", Vertical)
        box.border_title = "((●)) OPENBAND · ARCHIVAL TRANSCRIPT VIEWER"
        box.border_subtitle = "LOCAL TEXT STEWARDSHIP"
        self._render_transcript("")
        self.query_one("#tx-scroll", VerticalScroll).focus()

    def _render_transcript(self, query: str) -> None:
        q = query.strip().lower()
        t = Text()
        matches = 0
        for line in self.raw_text.splitlines():
            if not q:
                t.append("  " + line + "\n", style=AMBER)
            elif q in line.lower():
                matches += 1
                t.append("▸ " + line + "\n", style=f"bold {SIGNAL}")
            else:
                t.append("  " + line + "\n", style=DIM)
        self.query_one("#tx-body", Static).update(t)
        if q:
            self.query_one("#tx-meta", Static).update(
                Text(f"SEARCH: {matches} matching line(s) for {query!r} in {self.transcript_path.name}", style=SIGNAL if matches else ORANGE)
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "tx-search":
            self._render_transcript(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tx-search":
            self.query_one("#tx-scroll", VerticalScroll).focus()

    def action_focus_search(self) -> None:
        self.query_one("#tx-search", Input).focus()

    def action_close(self) -> None:
        self.dismiss(None)


class CatalogScreen(ModalScreen):
    """F4 Commons Catalog — searchable local archive with M3U8/Markdown/CSV export and Offline Transcript Reader."""

    BINDINGS = [
        ("escape", "close", "CLOSE"),
        ("o", "open_dir", "OPEN FOLDER"),
        ("u", "use_url", "LOAD URL"),
        ("t", "read_transcript", "TRANSCRIPT"),
        ("e", "export_archive", "EXPORT M3U8/MD/CSV"),
        ("slash", "focus_search", "SEARCH"),
    ]

    def __init__(self, entries: Optional[list[core.CatalogEntry]] = None):
        super().__init__()
        self.all_entries = entries if entries is not None else core.load_catalog()
        self.filtered: list[core.CatalogEntry] = list(self.all_entries)

    def compose(self) -> ComposeResult:
        total_bytes = sum(e.size for e in self.all_entries if e.size)
        size_badge = f"  ·  {kb.fmt_size(total_bytes)} PRESERVED LOCALLY" if total_bytes else ""
        with Vertical(id="cat-box"):
            yield Static(
                Text.assemble(
                    ("((●)) COMMONS CATALOG ▸ ", SIGNAL),
                    (f"{len(self.all_entries)} ARCHIVED ITEMS{size_badge}", f"bold {BRIGHT}"),
                ),
                id="cat-title",
            )
            yield Input(placeholder="filter local archive by title, creator, or codec spec… (press / to focus)", id="cat-search")
            yield DataTable(id="cat-table", cursor_type="row", zebra_stripes=False, cell_padding=1)
            yield Static(id="cat-detail")
            yield Static(
                "ENTER open   ·   T read transcript   ·   E export M3U8/MD/CSV   ·   O folder   ·   U load URL   ·   / filter   ·   ESC close",
                id="cat-keys",
            )

    def on_mount(self) -> None:
        box = self.query_one("#cat-box", Vertical)
        box.border_title = "((●)) OPENBAND · LOCAL COMMONS ARCHIVE"
        box.border_subtitle = "YOUR MEDIA. YOUR TERMS."
        table = self.query_one("#cat-table", DataTable)
        table.add_columns("ARCHIVED", "TITLE", "CREATOR", "SPEC", "SIZE")
        self._populate_table("")
        table.focus()

    def _populate_table(self, query: str) -> None:
        q = query.strip().lower()
        self.filtered = [
            e for e in self.all_entries
            if not q or q in e.title.lower() or q in e.channel.lower() or q in e.spec.lower()
        ]
        table = self.query_one("#cat-table", DataTable)
        table.clear()
        for i, e in enumerate(self.filtered):
            t_short = e.title if len(e.title) <= 34 else e.title[:33] + "…"
            c_short = e.channel if len(e.channel) <= 16 else e.channel[:15] + "…"
            table.add_row(
                e.archived_at[:10],
                t_short,
                c_short,
                e.spec[:22],
                Text(kb.fmt_size(e.size), justify="right"),
                key=str(i),
            )
        if self.filtered:
            self._show_detail(0)
        else:
            self.query_one("#cat-detail", Static).update(
                Text("No matching items in local Commons Catalog (~/.openband_catalog.json).", style=DIM)
            )

    def _show_detail(self, index: int) -> None:
        if not 0 <= index < len(self.filtered):
            return
        e = self.filtered[index]
        exists = os.path.exists(e.path) if e.path else False
        tx_path = core.find_transcript_for_media(e.path) if e.path else None
        nfo_exists = os.path.exists(os.path.splitext(e.path)[0] + ".nfo") if e.path else False
        t = Text()
        t.append(f"{e.title}\n", style=f"bold {BRIGHT}")
        t.append(f"SOURCE: {e.url}   ·   SPEC: {e.spec}\n", style=AMBER)
        status = "● VERIFIED ON DISK (USER OWNED)" if exists else "○ FILE MOVED OR RENAMED"
        extras = []
        if nfo_exists:
            extras.append("+NFO")
        if tx_path:
            extras.append("+TRANSCRIPT (press T)")
        extra_str = ("  [" + " · ".join(extras) + "]") if extras else ""
        t.append(f"LOCAL:  {e.path}  [{status}]{extra_str}", style=SIGNAL if exists else ORANGE)
        self.query_one("#cat-detail", Static).update(t)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "cat-search":
            self._populate_table(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "cat-search":
            self.query_one("#cat-table", DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_detail(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self.filtered):
            entry = self.filtered[event.cursor_row]
            if entry.path and os.path.exists(entry.path):
                core.open_file(entry.path)

    def action_read_transcript(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        if not (0 <= table.cursor_row < len(self.filtered)):
            return
        entry = self.filtered[table.cursor_row]
        tx_path = core.find_transcript_for_media(entry.path)
        if tx_path and tx_path.is_file():
            self.app.push_screen(TranscriptScreen(entry.title, tx_path))
        else:
            self.app.notify("No local .transcript.txt found for this item (use SUBS → CLEAN TXT when downloading)", severity="warning", timeout=4)

    def action_export_archive(self) -> None:
        if not self.all_entries:
            self.app.notify("Catalog is empty — archive media first before exporting", severity="warning", timeout=3)
            return
        try:
            m3u_p = core.export_catalog_m3u8(self.all_entries)
            md_p = core.export_catalog_markdown(self.all_entries)
            csv_p = core.export_catalog_csv(self.all_entries)
            msg = f"Exported playlist & ledger: {m3u_p.name}, {md_p.name}, {csv_p.name} in {m3u_p.parent}"
            self.query_one("#cat-detail", Static).update(Text("✓ " + msg, style=f"bold {SIGNAL}"))
            self.app.notify(msg, timeout=5)
        except Exception as e:  # noqa: BLE001
            self.app.notify(f"Export failed: {e}", severity="error", timeout=4)

    def action_open_dir(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        if 0 <= table.cursor_row < len(self.filtered):
            entry = self.filtered[table.cursor_row]
            folder = os.path.dirname(entry.path) if entry.path else "."
            if os.path.isdir(folder):
                core.open_folder(folder)

    def action_use_url(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        if 0 <= table.cursor_row < len(self.filtered):
            self.dismiss(self.filtered[table.cursor_row].url)

    def action_focus_search(self) -> None:
        self.query_one("#cat-search", Input).focus()

    def action_close(self) -> None:
        self.dismiss(None)


class BatchImportScreen(ModalScreen):
    """Ctrl+B Batch URL Importer — load a file of URLs or paste a multi-line list into the download queue."""

    BINDINGS = [
        ("escape", "close", "CANCEL"),
        ("f5", "enqueue_all", "ENQUEUE ALL"),
        ("ctrl+enter", "enqueue_all", "ENQUEUE ALL"),
        ("ctrl+l", "load_file", "LOAD FILE"),
    ]

    def __init__(self, initial_text: str = ""):
        super().__init__()
        self.initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(id="batch-box"):
            yield Static(
                Text.assemble(
                    ("((●)) BATCH SIGNAL IMPORTER ▸ ", SIGNAL),
                    ("MULTI-URL QUEUE & FILE LOADER", f"bold {BRIGHT}"),
                ),
                id="batch-title",
            )
            yield Input(
                placeholder="optional: path to URL list file (e.g. ~/urls.txt) — press ENTER to load file into editor",
                id="batch-file",
            )
            yield TextArea(self.initial_text, id="batch-area")
            yield Static(id="batch-status")
            yield Static(
                "F5 enqueue all valid URLs   ·   ENTER (in file box) load file   ·   ESC cancel",
                id="batch-keys",
            )

    def on_mount(self) -> None:
        box = self.query_one("#batch-box", Vertical)
        box.border_title = "((●)) OPENBAND · BATCH QUEUE IMPORTER"
        box.border_subtitle = "YOUTUBE · SPOTIFY · INSTAGRAM · X · FACEBOOK"
        area = self.query_one("#batch-area", TextArea)
        area.focus()
        self._update_preview()

    def _update_preview(self) -> None:
        raw = self.query_one("#batch-area", TextArea).text
        urls = core.parse_batch_urls(raw)
        valid = []
        unsupported = 0
        counts: dict[str, int] = {}
        for u in urls:
            d = platforms.detect_platform(u)
            if d.supported:
                valid.append(u)
                counts[d.spec.badge] = counts.get(d.spec.badge, 0) + 1
            else:
                unsupported += 1
        status = self.query_one("#batch-status", Static)
        if not urls:
            status.update(Text("Paste one URL per line (lines starting with # are ignored), or load a .txt/.md file above.", style=DIM))
        else:
            breakdown = " · ".join(f"{k}: {v}" for k, v in counts.items())
            warn_part = f"  ({unsupported} unsupported skipped)" if unsupported else ""
            status.update(
                Text(f"▸ {len(valid)} valid media URL(s) ready [{breakdown}]{warn_part} — press F5 to enqueue all", style=f"bold {SIGNAL}")
            )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "batch-area":
            self._update_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "batch-file":
            self.action_load_file()

    def action_load_file(self) -> None:
        path_str = self.query_one("#batch-file", Input).value.strip()
        if not path_str:
            return
        try:
            urls = core.load_batch_file(path_str)
            area = self.query_one("#batch-area", TextArea)
            existing = area.text.strip()
            joined = "\n".join(urls)
            area.text = (existing + "\n" + joined).strip() if existing else joined
            self._update_preview()
            area.focus()
        except Exception as e:  # noqa: BLE001
            self.query_one("#batch-status", Static).update(Text(f"× {e}", style=RED))

    def action_enqueue_all(self) -> None:
        raw = self.query_one("#batch-area", TextArea).text
        urls = [u for u in core.parse_batch_urls(raw) if platforms.detect_platform(u).supported]
        if not urls:
            self.query_one("#batch-status", Static).update(Text("! No valid supported media URLs found to enqueue.", style=ORANGE))
            return
        self.dismiss(urls)

    def action_close(self) -> None:
        self.dismiss(None)
