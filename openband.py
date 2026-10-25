#!/usr/bin/env python3
"""OpenBand — A Movement for Free Media.

An open-signal, archival multi-platform terminal front-end for yt-dlp.
Supports YouTube, Spotify (tracks, playlists, podcasts), Instagram (Reels, posts, Stories),
X / Twitter (video posts, broadcasts, Spaces), Facebook (Watch, Reels, videos), and web streams.

    pipx install .                        # one-command global CLI install
    openband                              # full cinematic launch
    openband --fast                       # skip opening sequence (or set OPENBAND_NO_SPLASH=1)
    openband --batch-file urls.txt -p 2   # batch import URLs with Full Archive preset
    openband --export-catalog             # export Commons Catalog to .m3u8, .md, and .csv

Keys:  ENTER download/queue · F2 scan · F3 formats · F4 catalog · F5 download · ESC cancel
       F6 open folder · F7 options · F8 cycle plate · F10 copy CLI · ^G paste&scan
       ^B batch import · Alt+1..4 presets · F9 update yt-dlp · F1 setup · Ctrl+Q quit
"""
from ytdl.app import main

if __name__ == "__main__":
    main()
