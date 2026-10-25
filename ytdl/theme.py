"""theme — OpenBand Movement visual identity: Archival Carbon, Newsprint Ivory, and Signal Gold."""
from textual.theme import Theme

# High-craft archival monochrome foundations with deliberate Signal Gold accent on deep carbon
AMBER, DIM, BRIGHT, ORANGE, RED = "#d8d8e0", "#767684", "#f4f4f8", "#e6a84c", "#e05850"
SIGNAL = "#e6a84c"
BLACK, PANEL = "#070709", "#131319"

PHOSPHOR = Theme(
    name="phosphor",
    primary=AMBER, secondary=DIM, accent=SIGNAL,
    warning=ORANGE, error=RED, success=BRIGHT,
    foreground=AMBER, background=BLACK, surface=BLACK, panel=PANEL,
    dark=True,
    variables={
        "input-cursor-background": BLACK,
        "input-cursor-foreground": BRIGHT,
        "input-selection-background": f"{SIGNAL} 35%",
        "footer-key-foreground": BLACK,
        "footer-key-background": SIGNAL,
        "footer-description-foreground": BRIGHT,
        "footer-description-background": "transparent",
        "footer-item-background": "transparent",
        "footer-background": "transparent",
        "block-hover-background": PANEL,
    },
)

CSS = """
Screen { padding: 0 2; background: $background; color: $foreground; }

/* top masthead & movement status bar */
#head { height: 1; margin-top: 1; align: left middle; }
#logo { width: 1fr; }
#env { width: auto; }
#greet-bar { height: 1; color: $accent; margin-bottom: 0; }
Rule { width: 100%; margin: 0; color: $secondary; }

/* symmetrical 2-column main deck (fixed 13-row height so left & right borders align to the exact row) */
#top { height: 13; margin-top: 1; }
#left-col { width: 1fr; height: 100%; border: solid $secondary; padding: 0 1; border-title-color: $accent; border-title-style: bold; border-subtitle-color: $secondary; }
#right-col { width: 52; height: 100%; margin-left: 2; border: solid $secondary; padding: 0 1; border-title-color: $accent; border-title-style: bold; border-subtitle-color: $secondary; background: $background; }

/* aligned form rows inside #left-col */
#opts { height: 1; }
.row { height: 1; align: left middle; margin-bottom: 0; }
.gap { margin-top: 1; }
.key { width: 9; color: $accent; text-style: bold; }
.sub { width: 7; color: $secondary; padding-left: 1; }
.hint { height: 1; color: $secondary; }
#more { height: auto; }

/* unified middle split bar: OUTPUT PREVIEW (left) + FIELD GUIDE (right) */
#mid { height: 7; margin-top: 1; }
Panel { border: solid $secondary; padding: 0 1; border-title-color: $accent; border-title-style: bold; border-subtitle-color: $secondary; background: transparent; }
#card { width: 1fr; height: 100%; }
#learn { width: 52; height: 100%; margin-left: 2; }

/* progress & log deck */
#prog-row { height: 1; margin-top: 1; margin-bottom: 0; padding: 0 1; }
RichLog { height: 1fr; min-height: 4; margin-top: 1; border: solid $secondary; border-title-color: $accent; border-title-style: bold;
          border-subtitle-color: $secondary; padding: 0 1; background: transparent; color: $foreground;
          scrollbar-size-vertical: 1; scrollbar-background: $background; scrollbar-color: $secondary;
          scrollbar-background-hover: $background; scrollbar-color-hover: $accent; }

/* responsive narrow terminal fallback (<106 cols) */
.narrow #top { layout: vertical; height: auto; }
.narrow #left-col { width: 100%; height: auto; }
.narrow #right-col { width: 100%; height: 9; margin-left: 0; margin-top: 1; }
.narrow #mid { layout: vertical; height: auto; }
.narrow #card { width: 100%; height: auto; min-height: 6; }
.narrow #learn { display: none; }

/* uniform input & select controls */
Input { width: 1fr; height: 1; border: none; padding: 0 1; background: $panel; color: $foreground; }
Input > .input--placeholder { color: $secondary; }
Input:focus { border: none; background: $accent; color: $background; text-style: bold; }
Input:focus > .input--placeholder { color: $background 60%; }
Input:disabled { opacity: 0.4; }

Select { width: 14; height: 1; margin-right: 1; }
#video-row Select, #audio-row Select { width: 12; margin-right: 1; }
SelectCurrent { border: none; height: 1; padding: 0 1; background: $panel; color: $foreground; }
SelectCurrent .arrow { color: $secondary; }
Select:focus > SelectCurrent { border: none; background: $accent; color: $background; text-style: bold; }
Select:focus > SelectCurrent .arrow { color: $background; }
SelectCurrent.-has-value Static#label { color: $foreground; }
Select:focus > SelectCurrent.-has-value Static#label { color: $background; }
Select:disabled { opacity: 0.4; }
SelectOverlay { border: solid $accent; background: $background; color: $foreground; }
SelectOverlay > .option-list--option-highlighted { background: $accent; color: $background; text-style: bold; }

RadioSet { width: auto; height: 1; border: none; padding: 0; background: transparent; layout: horizontal; }
RadioSet:focus { border: none; background: transparent; }
RadioButton { width: 13; height: 1; padding: 0 1 0 0; border: none; background: transparent; color: $foreground; }
RadioButton:focus { border: none; background: transparent; background-tint: transparent; }
RadioButton > .toggle--button, Checkbox > .toggle--button { color: $secondary; background: $panel; }
RadioButton.-on > .toggle--button, Checkbox.-on > .toggle--button { color: $accent; background: $panel; }
RadioSet > RadioButton.-selected > .toggle--label { background: transparent; color: $foreground; }
RadioSet:focus > RadioButton.-selected > .toggle--label,
RadioSet:focus > RadioButton:focus > .toggle--label { background: $accent; color: $background; text-style: bold; }
RadioButton:focus > .toggle--label { background: transparent; color: $foreground; }
RadioButton:blur:hover > .toggle--label { background: transparent; }

Checkbox { width: auto; height: 1; padding: 0 1 0 1; border: none; background: transparent; color: $foreground; }
Checkbox:focus { border: none; background: transparent; background-tint: transparent; }
Checkbox:focus > .toggle--label { background: $accent; color: $background; text-style: bold; }

Footer { background: transparent; }
FooterKey { margin-right: 1; }
Toast { background: $panel; color: $foreground; border: none; border-left: thick $accent; }
Toast.-warning { border-left: thick $warning; }
Toast.-error { border-left: thick $error; }

/* format browser, catalog, batch import, transcript reader & manifesto screen (modals) */
FormatScreen, ManifestoScreen, CatalogScreen, BatchImportScreen, TranscriptScreen { align: center middle; background: $background 92%; }
#batch-box, #tx-box { width: 88; max-width: 96%; height: auto; max-height: 92%; border: double $accent; background: $background; padding: 1 3; border-title-color: $accent; border-title-style: bold; border-subtitle-color: $secondary; }
#batch-title, #tx-title { color: $accent; text-style: bold; margin-bottom: 1; }
#batch-file, #tx-search { margin-bottom: 1; }
#batch-area { height: 10; min-height: 6; margin-bottom: 1; border: solid $secondary; background: $panel; color: $foreground; }
#batch-area:focus { border: solid $accent; }
#batch-status, #tx-meta { color: $foreground; margin-top: 0; }
#tx-scroll { height: auto; max-height: 18; min-height: 10; padding: 1 1; border-top: dashed $secondary; border-bottom: dashed $secondary; background: transparent; scrollbar-size-vertical: 1; scrollbar-background: $background; scrollbar-color: $secondary; scrollbar-color-hover: $accent; }
#tx-body { height: auto; width: 100%; }
#batch-keys, #tx-keys { color: $accent; margin-top: 1; text-style: bold; }
#fmt-box, #cat-box { width: 96; max-width: 96%; height: auto; max-height: 90%; border: double $accent; background: $background; padding: 1 2; }
#fmt-title, #cat-title { color: $accent; text-style: bold; margin-bottom: 1; }
#cat-search { margin-bottom: 1; }
#fmt-table, #cat-table { height: auto; max-height: 14; background: transparent; border: none; padding: 0; }
DataTable > .datatable--header { background: transparent; color: $accent; text-style: bold; }
DataTable > .datatable--cursor { background: $accent; color: $background; text-style: bold; }
DataTable > .datatable--hover { background: $panel; }
#fmt-learn, #cat-detail { margin-top: 1; height: auto; min-height: 3; border-top: dashed $secondary; padding-top: 1; color: $foreground; }
#fmt-keys, #cat-keys { color: $secondary; margin-top: 1; }

#manifesto-box { width: 80; max-width: 96%; height: auto; max-height: 92%; border: double $accent; background: $background; padding: 1 3; border-title-color: $accent; border-title-style: bold; border-subtitle-color: $secondary; }
#manifesto-header { color: $accent; text-style: bold; margin-bottom: 1; }
#manifesto-scroll { height: auto; max-height: 22; min-height: 15; padding: 1 1; border-top: dashed $secondary; border-bottom: dashed $secondary; background: transparent; scrollbar-size-vertical: 1; scrollbar-background: $background; scrollbar-color: $secondary; scrollbar-color-hover: $accent; }
#manifesto-stage { height: auto; width: 100%; }
#manifesto-concept { color: $foreground; margin-top: 1; }
#manifesto-keys { color: $accent; margin-top: 1; text-style: bold; }
"""
