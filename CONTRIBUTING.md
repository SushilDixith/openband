# Contributing to OpenBand

Thank you for helping build **OpenBand** — an open-signal, archival multi-platform terminal front-end for user-owned media.

## Development Setup

```bash
git clone https://github.com/<your-username>/openband.git
cd openband
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

## Running the Test Suite

All logic, multi-platform URL detection, format selection, transcript cleaning, catalog exports, and obfuscation audits are tested without requiring network calls:

```bash
python -B -m unittest discover -s tests -v
```

## Core Design Principles

1. **User Stewardship Over Lock-In**: Prioritize open containers (`MP4`, `MKV`, `FLAC`, `OPUS`, `WebVTT`, `.nfo`, `.m3u8`) and local ownership.
2. **Respect Creators & Boundaries**: Never implement DRM bypasses, credential harvesting, or simulated progress bars. Always redact session cookies from logs.
3. **Editorial Craft**: Preserve the Archival Carbon (`#070709`), Newsprint Ivory (`#f4f4f8`), and Signal Gold (`#e6a84c`) visual identity and 7-bit ASCII fallback compatibility.
