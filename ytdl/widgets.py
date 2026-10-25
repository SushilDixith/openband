"""widgets — small reusable OpenBand TUI components."""
from typing import Optional

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from . import manifesto
from .theme import AMBER, BRIGHT, DIM, ORANGE, RED, SIGNAL


class Panel(Static):
    """A bordered box with a title in its top edge."""

    def __init__(self, title: str, subtitle: str = "", **kwargs):
        super().__init__("", **kwargs)
        self.border_title = title
        if subtitle:
            self.border_subtitle = subtitle


class ManifestoBanner(Static):
    """Reusable monochrome terminal art and manifesto quote component for OpenBand.

    Supports independent or linked rotation of artwork and quotes, plus optional auto-cycle.
    """

    scene_index = reactive(0)
    quote_index = reactive(0)

    def __init__(self, initial_index: int = 0, initial_quote: Optional[int] = None, **kwargs):
        super().__init__("", **kwargs)
        self.scene_index = initial_index
        self.quote_index = initial_index if initial_quote is None else initial_quote
        self._sync_frame()

    def _current_dimensions(self) -> tuple[int, int]:
        try:
            w = self.size.width if self.size and self.size.width > 0 else 48
            h = self.size.height if self.size and self.size.height > 0 else 11
            return max(16, w - 2), max(6, h - 2)
        except Exception:  # noqa: BLE001
            return 48, 11

    def current_composition(self) -> manifesto.Composition:
        return manifesto.get_composition(self.scene_index, self.quote_index)

    def _sync_frame(self) -> None:
        comp = self.current_composition()
        total = len(manifesto.ARTWORKS)
        self.border_title = f"((●)) PLATE {(self.scene_index % total) + 1:02d}/{total:02d} · {comp.artwork.title}"
        self.border_subtitle = f"{comp.slogan} · F8 CYCLE"
        w, h = self._current_dimensions()
        self.update(manifesto.render_composition(comp, width=w, height=h, show_attribution=True))

    def watch_scene_index(self, new_index: int) -> None:
        self._sync_frame()

    def watch_quote_index(self, new_index: int) -> None:
        self._sync_frame()

    def on_resize(self) -> None:
        self._sync_frame()

    def next_scene(self, step: int = 1) -> manifesto.Composition:
        self.scene_index = (self.scene_index + step) % len(manifesto.ARTWORKS)
        self.quote_index = (self.quote_index + step) % len(manifesto.QUOTES)
        return self.current_composition()


class Gauge(Widget):
    """Signal-inspired transmission gauge:  ▐██████░░░░░░░░▌  42%  ((●)) 2/5  3.1 MiB/s"""

    DEFAULT_CSS = "Gauge { width: 1fr; height: 1; }"
    TAIL = 26  # fixed width for the text after the bar, so the bar never jitters
    PULSE = ("((·))", "((●))", "((◉))", "((●))")

    fraction = reactive(0.0)
    label = reactive("idle · carrier ready")
    tick = reactive(0)

    def render(self) -> Text:
        pct = f"{round(self.fraction * 100):>3}%"
        inner = max(8, self.size.width - self.TAIL - 8)
        filled = round(inner * min(max(self.fraction, 0.0), 1.0))

        bar_style = SIGNAL
        label_style = DIM
        prefix = ""
        lbl = self.label or "idle"

        if "fail" in lbl or "error" in lbl:
            bar_style = RED
            label_style = RED
            prefix = "× "
        elif "cancel" in lbl:
            bar_style = ORANGE
            label_style = ORANGE
            prefix = "○ "
        elif lbl.startswith("done") or lbl.startswith("archived") or lbl == "scanned":
            bar_style = BRIGHT
            label_style = f"bold {BRIGHT}"
            prefix = "✓ "
        elif 0.0 < self.fraction < 1.0 or lbl.startswith(("scanning", "starting", "resolving", "retry")):
            pulse_glyph = self.PULSE[self.tick % len(self.PULSE)]
            prefix = f"{pulse_glyph} "
            label_style = SIGNAL

        t = Text(no_wrap=True, overflow="crop")
        t.append("▐", style=DIM)
        t.append("█" * filled, style=bar_style)
        t.append("░" * (inner - filled), style=DIM)
        t.append("▌", style=DIM)
        t.append(f" {pct}  ", style=f"bold {BRIGHT}" if self.fraction >= 1.0 else f"bold {AMBER}")
        full_lbl = (prefix + lbl).ljust(self.TAIL)[: self.TAIL]
        t.append(full_lbl, style=label_style)
        return t
