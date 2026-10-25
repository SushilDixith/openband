"""Logic & Manifesto tests — no network, no UI.   Run:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import yt_dlp  # noqa: E402
    HAS_YTDLP = True
except ModuleNotFoundError:
    HAS_YTDLP = False

from ytdl import core, knowledge as kb, manifesto, platforms, spotify  # noqa: E402

R = core.FormatRow


def sample_rows():
    return [
        R(2160, 30, "vp9", "vp09", "webm", 1_400_000_000), R(2160, 30, "av1", "av01", "mp4", 900_000_000),
        R(1080, 60, "vp9", "vp09", "webm", 330_000_000), R(1080, 30, "h264", "avc1", "mp4", 180_000_000),
        R(1080, 30, "vp9", "vp09", "webm", 120_000_000), R(720, 30, "h264", "avc1", "mp4", 90_000_000, has_audio=True),
    ]


class Codecs(unittest.TestCase):
    def test_family(self):
        cases = {"avc1.640028": "h264", "vp09.00.40.08": "vp9", "vp9": "vp9", "av01.0.08M.08": "av1",
                 "hev1.1.6.L93": "h265", "hvc1": "h265", "theora": "other", "none": None, None: None}
        for raw, want in cases.items():
            self.assertEqual(core.codec_family(raw), want, raw)

    def test_audio_family(self):
        self.assertEqual(core.audio_family("mp4a.40.2"), "AAC")
        self.assertEqual(core.audio_family("opus"), "Opus")
        self.assertIsNone(core.audio_family("none"))


class Selectors(unittest.TestCase):
    @unittest.skipUnless(HAS_YTDLP, "yt_dlp not installed in environment")
    def test_selectors_are_valid_yt_dlp(self):
        ydl = yt_dlp.YoutubeDL({"quiet": True})
        for codec in (None, "h264", "h265", "vp9", "av1"):
            for res in (None, 720, 2160):
                for merge in (True, False):
                    ydl.build_format_selector(core.build_video_format(res, codec, merge))

    def test_mp4_codecs_prefer_aac(self):
        self.assertIn("ba[ext=m4a]", core.build_video_format(1080, "h264"))
        self.assertNotIn("ba[ext=m4a]", core.build_video_format(1080, "vp9"))

    def test_no_ffmpeg_means_single_files(self):
        self.assertEqual(core.build_video_format(720, "h264", can_merge=False), "b[height<=720]/b")


class Picking(unittest.TestCase):
    def test_codec_wins_within_cap(self):
        row, fell = core.pick_row(sample_rows(), None, "h264", False)
        self.assertEqual((row.height, row.codec, fell), (1080, "h264", False))

    def test_h264_never_reaches_4k(self):
        row, _ = core.pick_row(sample_rows(), 2160, "h264", False)
        self.assertEqual(row.height, 1080)

    def test_fallback_when_codec_absent(self):
        row, fell = core.pick_row(sample_rows(), None, "h265", False)
        self.assertTrue(fell)
        self.assertEqual(row.height, 2160)

    def test_no_merge_prefers_premerged_stream(self):
        row, _ = core.pick_row(sample_rows(), None, "h264", False, can_merge=False)
        self.assertEqual(row.height, 720)
        self.assertTrue(row.has_audio)

    def test_fps_preference(self):
        self.assertEqual(core.pick_row(sample_rows(), 1080, "vp9", True)[0].fps, 60)
        self.assertEqual(core.pick_row(sample_rows(), 1080, "vp9", False)[0].fps, 30)

    def test_auto_prefers_newest_codec(self):
        self.assertEqual(core.pick_row(sample_rows(), None, None, False)[0].codec, "av1")

    def test_estimate(self):
        audio = core.AudioFacts(9_000_000, 129, "Opus")
        self.assertEqual(core.estimate_size(sample_rows()[3], audio), 189_000_000)
        self.assertEqual(core.estimate_size(sample_rows()[5], audio), 90_000_000)
        self.assertIsNone(core.estimate_size(None, audio))


class Scanning(unittest.TestCase):
    def test_summarize_and_scan(self):
        info = {"title": "T", "duration": 100, "upload_date": "20080410", "channel": "C", "formats": [
            {"vcodec": "avc1.64", "acodec": "none", "height": 1080, "fps": 30, "tbr": 2000, "ext": "mp4"},
            {"vcodec": "avc1.64", "acodec": "none", "height": 1080, "fps": 30, "tbr": 3000, "ext": "mp4"},
            {"vcodec": "vp09", "acodec": "none", "height": 1080, "fps": 60, "tbr": 4000, "ext": "webm", "filesize": 7},
            {"vcodec": "none", "acodec": "opus", "abr": 130, "tbr": 130, "ext": "webm"},
            {"vcodec": "none", "acodec": "none", "ext": "mhtml"},
        ]}
        orig = core._extract
        core._extract = lambda *a, **k: info
        try:
            s = core.scan("u")
        finally:
            core._extract = orig
        self.assertEqual(len(s.rows), 2)
        self.assertEqual(s.rows[0].fps, 60)
        self.assertEqual(s.availability, {"vp9": 1080, "h264": 1080})
        self.assertEqual(s.upload_date, "2008-04-10")
        self.assertEqual((s.audio.codec, s.audio.abr), ("Opus", 130))
        self.assertEqual(next(r for r in s.rows if r.codec == "h264").size, int(3000 * 1000 / 8 * 100))


class Options(unittest.TestCase):
    def test_rate_limit(self):
        self.assertEqual(core.parse_rate_limit("1M"), 1_000_000)
        self.assertEqual(core.parse_rate_limit("2.5MB/s"), 2_500_000)
        self.assertEqual(core.parse_rate_limit("500k"), 500_000)
        self.assertEqual(core.parse_rate_limit("120000"), 120_000)
        self.assertIsNone(core.parse_rate_limit("0"))
        self.assertIsNone(core.parse_rate_limit("0M"))
        self.assertIsNone(core.parse_rate_limit("abc"))
        self.assertIsNone(core.parse_rate_limit(""))

    def test_time_range_parsing(self):
        self.assertEqual(core.parse_time_range("01:20-04:15"), (80.0, 255.0))
        self.assertEqual(core.parse_time_range("*90-180"), (90.0, 180.0))
        self.assertEqual(core.parse_time_range("01:02:03-01:05:00"), (3723.0, 3900.0))
        self.assertIsNone(core.parse_time_range("05:00-02:00"))
        self.assertIsNone(core.parse_time_range("invalid"))
        self.assertIsNone(core.parse_time_range(""))

    def test_ydl_opts_and_archival_features(self):
        o = core.DownloadOptions(
            "https://example.com/v", "o", False, "video", None, None, "vp9", 1080, True, None, None,
            archive_bundle=True, split_chapters=True, subs_mode="en",
            cookies_from_browser="firefox", time_range="01:00-02:30",
        )
        opts = core.build_ydl_opts(o, lambda d: None, None, on_file=print, can_merge=True)
        self.assertEqual(opts["format_sort"], ["res", "fps"])
        self.assertIn("post_hooks", opts)
        self.assertEqual(opts["cookiesfrombrowser"], ("firefox",))
        self.assertTrue(opts["writesubtitles"])
        self.assertTrue(opts["writethumbnail"])
        self.assertIn("download_ranges", opts)
        pp_keys = [p["key"] for p in opts["postprocessors"]]
        self.assertIn("FFmpegMetadata", pp_keys)
        self.assertIn("FFmpegEmbedSubtitle", pp_keys)
        self.assertIn("EmbedThumbnail", pp_keys)
        self.assertIn("FFmpegSplitChapters", pp_keys)

        # CLI preview verification
        cli = core.build_cli_command(o, can_merge=True)
        self.assertIn("--embed-metadata", cli)
        self.assertIn("--split-chapters", cli)
        self.assertIn("--cookies-from-browser firefox", cli)
        self.assertIn("--download-sections", cli)

        a = core.DownloadOptions("u", "o", False, "audio", "mp3", "256", None, None, False, None, None)
        pp = core.build_ydl_opts(a, lambda d: None, None)["postprocessors"][0]
        self.assertEqual((pp["preferredcodec"], pp["preferredquality"]), ("mp3", "256"))
        flac = core.DownloadOptions("u", "o", False, "audio", "flac", "320", None, None, False, None, None)
        pp_flac = core.build_ydl_opts(flac, lambda d: None, None)["postprocessors"][0]
        self.assertNotIn("preferredquality", pp_flac)
        b = core.DownloadOptions("u", "o", False, "audio", "best", None, None, None, False, None, None)
        self.assertNotIn("postprocessors", core.build_ydl_opts(b, lambda d: None, None))

    def test_vtt_transcript_cleaner(self):
        sample_vtt = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.500
<c>Culture</c> should travel further

00:00:03.500 --> 00:00:06.000
Culture should travel further
than the paywall.
"""
        cleaned = core.vtt_to_clean_text(sample_vtt)
        self.assertEqual(cleaned, "Culture should travel further\nthan the paywall.")

        with tempfile.TemporaryDirectory() as tmpdir:
            vtt_file = Path(tmpdir) / "talk.en.vtt"
            vtt_file.write_text(sample_vtt, encoding="utf-8")
            out_files = core.write_clean_transcripts(tmpdir)
            self.assertEqual(len(out_files), 1)
            self.assertTrue(out_files[0].endswith(".transcript.txt"))
            self.assertIn("than the paywall.", Path(out_files[0]).read_text(encoding="utf-8"))

    def test_commons_catalog_and_presets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cat_file = Path(tmpdir) / "catalog.json"
            self.assertEqual(core.load_catalog(cat_file), [])
            entry = core.CatalogEntry(
                title="Open Signal Documentary",
                channel="Commons",
                url="https://example.com/doc",
                spec="H.264 · 1080p · MP4",
                size=150_000_000,
                path="/tmp/doc.mp4",
                archived_at="2026-10-14 09:30",
            )
            core.append_catalog(entry, cat_file)
            loaded = core.load_catalog(cat_file)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].title, "Open Signal Documentary")
            core.clear_catalog(cat_file)
            self.assertEqual(core.load_catalog(cat_file), [])

        presets = core.load_presets()
        self.assertIn("1", presets)
        self.assertIn("2", presets)
        self.assertTrue(presets["2"].archive_bundle)


class Hook(unittest.TestCase):
    def test_two_streams_one_bar_and_report(self):
        pushed, items = [], {}
        hook = core.make_progress_hook(0, lambda f, l: pushed.append(f), lambda: False,
                                       on_item=lambda i, info: items.__setitem__(i, info))
        info = {
            "requested_formats": [
                {"vcodec": "avc1.640028", "acodec": "none", "height": 1080, "fps": 30, "ext": "mp4"},
                {"vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a"},
            ]
        }
        hook({"status": "downloading", "info_dict": info, "filename": "v", "downloaded_bytes": 50, "total_bytes": 100})
        hook({"status": "downloading", "info_dict": info, "filename": "v", "downloaded_bytes": 100, "total_bytes": 100})
        hook({"status": "finished", "info_dict": info, "filename": "v"})
        hook({"status": "downloading", "info_dict": info, "filename": "a", "downloaded_bytes": 50, "total_bytes": 100})
        hook({"status": "downloading", "info_dict": info, "filename": "a", "downloaded_bytes": 100, "total_bytes": 100})
        hook({"status": "finished", "info_dict": info, "filename": "a"})
        self.assertEqual(pushed[-1], 1.0)
        got = core.summarize_got(items[1])
        self.assertEqual((got.codec, got.acodec, got.height, got.ext), ("h264", "AAC", 1080, "mp4"))

    def test_cancel(self):
        with self.assertRaises(core.DownloadCancelled):
            core.make_progress_hook(0, print, lambda: True)({"status": "downloading"})


class Errors(unittest.TestCase):
    def test_friendly(self):
        cases = {
            "\x1b[0;31mERROR:\x1b[0m unable to download video data: HTTP Error 403: Forbidden": "403",
            "ERROR: [youtube] x: Private video. Sign in": "private",
            "ERROR: Requested format is not available. Use --list-formats": "format",
            "ERROR: Unsupported URL: foo": "isn't supported",
            "ERROR: <urlopen error [Errno 11001] getaddrinfo failed>": "reach",
        }
        for raw, needle in cases.items():
            f = core.friendly_error(raw)
            self.assertIn(needle.lower(), (f.headline + f.hint).lower(), raw)
            self.assertNotIn("\x1b", f.headline)
        self.assertEqual(core.friendly_error("ERROR: something odd").headline, "something odd")

    def test_versions(self):
        self.assertTrue(core.is_newer("2026.9.2", "2026.08.19"))
        self.assertFalse(core.is_newer("2026.8.19", "2026.08.19"))
        self.assertFalse(core.is_newer("2026.8.1", "2026.08.19"))


class Knowledge(unittest.TestCase):
    def test_every_codec_is_complete_and_card_sized(self):
        for key, c in kb.CODECS.items():
            for attr in ("name", "tagline", "detail", "plays_on", "container"):
                self.assertTrue(getattr(c, attr), f"{key}.{attr}")
            self.assertLessEqual(len(c.plays_on), 30, key)
        for key, a in kb.AUDIO.items():
            self.assertTrue(a.name and a.tagline and a.detail and a.plays_on, key)

    def test_every_topic_has_a_lesson(self):
        for topic in ("codec", "res", "fps", "mode", "scope", "aformat", "bitrate", "pattern",
                      "template", "url", "out", "limit", "proxy", "archive", "split", "subs", "cookies", "range"):
            self.assertTrue(kb.learn(topic, None).title, topic)
        for codec in ("none", "h264", "h265", "vp9", "av1"):
            self.assertTrue(kb.learn("codec", codec).tagline)
        for fmt in kb.AUDIO:
            self.assertTrue(kb.learn("aformat", fmt).body)
        self.assertIn("2160p", kb.learn("res", 2160).title)

    def test_facts_use_the_scan(self):
        view = kb.ScanView({"h264": 1080, "vp9": 2160}, [2160, 1080])
        self.assertIn("1080p", kb.learn("codec", "h264", view).facts)
        self.assertIn("no H.265", kb.learn("codec", "h265", view).facts)

    def test_formatting(self):
        self.assertEqual(kb.fmt_size(182_000_000), "182 MB")
        self.assertEqual(kb.fmt_size(1_400_000_000), "1.4 GB")
        self.assertEqual(kb.fmt_duration(596), "9:56")
        self.assertEqual(kb.fmt_duration(3723), "1:02:03")
        self.assertEqual(kb.fmt_duration(0), "0:00")
        self.assertEqual(kb.bars(3), "███░░")

    def test_summaries(self):
        rows = sample_rows()
        pick, fell = core.pick_row(rows, 2160, "h264", False)
        s = kb.describe_video(codec="h264", height=2160, prefer60=False, ffmpeg=True, row=pick, fell_back=fell,
                              offers={"vp9": 2160, "av1": 2160, "h264": 1080})
        self.assertIn("MP4 · H.264 · 1080p", s.spec)
        self.assertIn("VP9 or AV1 reach 2160p", s.notes[0])
        self.assertTrue(any("ffmpeg" in w for w in kb.describe_video(codec=None, height=None, prefer60=False, ffmpeg=False).warns))
        a = kb.describe_audio(fmt="mp3", bitrate=320, ffmpeg=True, duration=600)
        self.assertEqual(a.size, 24_000_000)
        self.assertTrue(a.warns)
        self.assertTrue(kb.describe_audio(fmt="wav", bitrate=None, duration=60, ffmpeg=True).warns)

    def test_report_explains_fallbacks(self):
        got = [core.Got("vp9", "Opus", 2160, 30, "mkv")]
        lines = kb.report_video(asked_codec="h264", asked_height=2160, asked_prefer60=False, gots=got,
                                availability={"h264": 1080, "vp9": 2160})
        text = "\n".join(t for t, _ in lines)
        self.assertIn("asked: H.264 · 2160p", text)
        self.assertIn("VP9 · 2160p · MKV · Opus", text)
        self.assertIn("only goes up to 1080p", text)
        self.assertEqual(kb.report_video(asked_codec=None, asked_height=None, asked_prefer60=False, gots=[]), [])


class ManifestoSystem(unittest.TestCase):
    def test_required_manifesto_quotes_present(self):
        required = [
            "Culture should travel further than the paywall.",
            "Information wants to be accessible.",
            "The internet was built to connect, not to exclude.",
            "Access should not depend on another monthly bill.",
            "A library is more powerful when its doors are open.",
            "Knowledge loses nothing when it is shared lawfully.",
            "The future of media should belong to its audience, too.",
            "Freedom begins where unnecessary barriers end.",
            "Not everything valuable needs another subscription.",
            "An open archive is a promise to the curious.",
        ]
        for q in required:
            self.assertIn(q, manifesto.QUOTES)

    def test_artwork_dimensions_and_ascii_compatibility(self):
        self.assertGreaterEqual(len(manifesto.ARTWORKS), 6)
        for art in manifesto.ARTWORKS:
            self.assertTrue(art.key and art.title and art.concept)
            self.assertEqual(len(art.full), 7, art.key)
            self.assertEqual(len(art.compact), 4, art.key)
            for line in art.full:
                self.assertLessEqual(len(line), 44, f"{art.key} full line too wide")
                self.assertTrue(line.isascii(), f"{art.key} full contains non-ASCII")
            for line in art.compact:
                self.assertLessEqual(len(line), 26, f"{art.key} compact line too wide")
                self.assertTrue(line.isascii(), f"{art.key} compact contains non-ASCII")

    def test_greeting_and_persistent_rotation_across_launches(self):
        g_morning = manifesto.build_greeting("alice", hour=9, session_number=1)
        self.assertIn("Welcome to OpenBand, alice", g_morning)
        self.assertIn("good morning", g_morning)

        g_night = manifesto.build_greeting("alice", hour=23, session_number=4)
        self.assertIn("Welcome to OpenBand, alice", g_night)
        self.assertIn("late shift", g_night)
        self.assertIn("session #4", g_night)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            s1, q1, sess1 = manifesto.next_startup_state(env_scene="", state_path=state_file)
            s2, q2, sess2 = manifesto.next_startup_state(env_scene="", state_path=state_file)
            s3, q3, sess3 = manifesto.next_startup_state(env_scene="", state_path=state_file)
            self.assertEqual((sess1, sess2, sess3), (1, 2, 3))
            self.assertEqual((s1, s2, s3), (0, 1, 2))
            self.assertEqual((q1, q2, q3), (0, 1, 2))

    def test_deterministic_selection_and_rotation(self):
        c0 = manifesto.get_composition(0)
        c0_again = manifesto.get_composition(0)
        self.assertEqual(c0, c0_again)
        c1 = manifesto.get_composition(1)
        self.assertNotEqual(c0.artwork.key, c1.artwork.key)
        self.assertNotEqual(c0.quote, c1.quote)
        self.assertEqual(manifesto.initial_scene_index("bridge"), 1)
        self.assertEqual(manifesto.initial_scene_index("2"), 2)
        self.assertEqual(manifesto.initial_scene_index(""), 0)

    def test_adaptive_rendering_full_compact_and_minimal(self):
        comp = manifesto.get_composition(0)
        full_text = manifesto.render_composition(comp, width=50, height=11)
        full_lines = full_text.plain.splitlines()
        self.assertLessEqual(len(full_lines), 11)
        self.assertGreaterEqual(len(full_lines), 9)
        for line in full_lines:
            self.assertLessEqual(len(line), 50)
        self.assertIn(comp.quote, full_text.plain)
        self.assertIn("OPENBAND · FREE MEDIA MANIFESTO", full_text.plain)

        compact_text = manifesto.render_composition(comp, width=30, height=8)
        compact_lines = compact_text.plain.splitlines()
        self.assertLessEqual(len(compact_lines), 8)
        for line in compact_lines:
            self.assertLessEqual(len(line), 30)

        tiny_text = manifesto.render_composition(comp, width=18, height=3)
        tiny_lines = tiny_text.plain.splitlines()
        self.assertLessEqual(len(tiny_lines), 3)
        for line in tiny_lines:
            self.assertLessEqual(len(line), 18)

        self.assertEqual(manifesto.render_composition(comp, width=0, height=0).plain, "")
        self.assertEqual(manifesto.render_composition(comp, width=-5, height=10).plain, "")

    def test_unicode_fallback(self):
        self.assertTrue(manifesto.supports_unicode("utf-8"))
        self.assertFalse(manifesto.supports_unicode("ascii"))
        comp = manifesto.get_composition(0)
        ascii_rendered = manifesto.render_composition(comp, width=50, height=11, unicode_ok=False)
        self.assertTrue(ascii_rendered.plain.isascii())
        self.assertIn("-- OPENBAND - FREE MEDIA MANIFESTO", ascii_rendered.plain)

    def test_wordmark_and_cinematic_opening_sequence(self):
        wm_full = manifesto.render_wordmark(width=60)
        self.assertEqual(len(wm_full.plain.splitlines()), 3)
        wm_compact = manifesto.render_wordmark(width=30)
        self.assertEqual(len(wm_compact.plain.splitlines()), 2)
        wm_inline = manifesto.render_wordmark(width=20)
        self.assertIn("OPENBAND", wm_inline.plain)

        comp = manifesto.get_composition(0)
        for step in (1, 2, 3, 4):
            frame = manifesto.render_opening_frame(comp, step=step, width=64)
            self.assertTrue(frame.plain.strip())
            if step >= 2:
                self.assertIn("A MOVEMENT FOR FREE MEDIA", frame.plain)
            if step == 4:
                self.assertIn("ARCHIVAL BUNDLES", frame.plain)

    def test_slogans_letter_and_exit_banner(self):
        self.assertGreaterEqual(len(manifesto.SLOGANS), 6)
        self.assertIn("ACCESS IS NOT OWNERSHIP.", manifesto.SLOGANS)
        self.assertIn("YOUR MEDIA. YOUR TERMS.", manifesto.SLOGANS)
        self.assertEqual(len(manifesto.MANIFESTO_TENETS), 5)

        # Verify the P glyph in WORDMARK_FULL has a closed loop (├───╯) and vertical stem (│)
        self.assertIn("├───╯", manifesto.WORDMARK_FULL[1])
        self.assertIn("├─╯", manifesto.WORDMARK_COMPACT[1])

        # Verify obfuscated carrier payload demodulates cleanly at runtime without plaintext in source
        self.assertTrue(len(manifesto.MANIFESTO_TITLE) > 10)
        self.assertEqual(len(manifesto.MANIFESTO_LETTER_PARAGRAPHS), 36)
        rendered_letter = manifesto.render_manifesto_letter(width=68)
        self.assertIn(manifesto.MANIFESTO_TITLE, rendered_letter.plain)
        self.assertIn(manifesto.MANIFESTO_LETTER_PARAGRAPHS[0], rendered_letter.plain)

        banner = manifesto.render_exit_banner(session_number=2, archived_count=5)
        self.assertIn("OPENBAND", banner)
        self.assertIn("5 ITEMS IN COMMONS CATALOG", banner)
        banner_ascii = manifesto.render_exit_banner(session_number=1, archived_count=0, unicode_ok=False)
        self.assertTrue(banner_ascii.isascii())



import json


class SpotifySupport(unittest.TestCase):
    def test_url_and_uri_parsing(self):
        cases = {
            "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=123": ("track", "4uLU6hMCjMI75M1A2tKUQC"),
            "https://open.spotify.com/intl-de/playlist/37i9dQZF1DXcBWIGoYBM5M": ("playlist", "37i9dQZF1DXcBWIGoYBM5M"),
            "https://open.spotify.com/album/1ATL5GLyefJaxhQzSPVrLX": ("album", "1ATL5GLyefJaxhQzSPVrLX"),
            "https://open.spotify.com/episode/512ojhOuo1ktJprKbVcKyQ": ("episode", "512ojhOuo1ktJprKbVcKyQ"),
            "https://open.spotify.com/show/2MAi0BvDc6GTFvKFPXnkCL": ("show", "2MAi0BvDc6GTFvKFPXnkCL"),
            "spotify:track:4uLU6hMCjMI75M1A2tKUQC": ("track", "4uLU6hMCjMI75M1A2tKUQC"),
            "spotify:episode:512ojhOuo1ktJprKbVcKyQ": ("episode", "512ojhOuo1ktJprKbVcKyQ"),
        }
        for url, want in cases.items():
            self.assertTrue(spotify.is_spotify_url(url), url)
            self.assertEqual(spotify.parse_spotify_url(url), want, url)
        self.assertFalse(spotify.is_spotify_url("https://www.youtube.com/watch?v=123"))
        self.assertIsNone(spotify.parse_spotify_url("https://example.com"))

    def test_embed_json_parsing_for_playlist_and_podcast(self):
        # 1. Playlist embed JSON
        playlist_payload = {
            "props": {
                "pageProps": {
                    "state": {
                        "data": {
                            "entity": {
                                "name": "Late Night Coding",
                                "subtitle": "OpenBand Curators",
                                "coverArt": {"sources": [{"url": "https://i.scdn.co/image/cover1"}]},
                                "trackList": [
                                    {"title": "Midnight Signal", "subtitle": "Synth Collective", "duration": 210000},
                                    {"title": "Open Frequency", "subtitle": "Modular Youth", "duration": 185000},
                                ],
                            }
                        }
                    }
                }
            }
        }
        html_page = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(playlist_payload)}</script></body></html>'
        next_data = spotify._extract_next_data(html_page)
        self.assertIsNotNone(next_data)
        res = spotify._parse_embed_entity(next_data, "playlist", "pl123", "https://open.spotify.com/playlist/pl123")
        self.assertEqual(res.title, "Late Night Coding")
        self.assertEqual(res.creator, "OpenBand Curators")
        self.assertEqual(len(res.items), 2)
        self.assertEqual(res.items[0].search_query, "Synth Collective - Midnight Signal official audio")
        self.assertEqual(res.items[0].fallback_query, "Synth Collective - Midnight Signal")
        self.assertEqual(res.duration, 395)

        # 2. Podcast Episode embed JSON
        ep_payload = {
            "props": {
                "pageProps": {
                    "state": {
                        "data": {
                            "entity": {
                                "title": "Episode 42: The Unwalled Web",
                                "show": {"name": "Free Media Podcast"},
                                "duration": 1800000,
                                "audioPreview": {"url": "https://p.scdn.co/mp3-preview/ep42"},
                            }
                        }
                    }
                }
            }
        }
        res_ep = spotify._parse_embed_entity(ep_payload, "episode", "ep42", "https://open.spotify.com/episode/ep42")
        self.assertEqual(res_ep.title, "Episode 42: The Unwalled Web")
        self.assertEqual(res_ep.creator, "Free Media Podcast")
        self.assertEqual(res_ep.items[0].kind, "episode")
        self.assertEqual(res_ep.items[0].search_query, "Free Media Podcast Episode 42: The Unwalled Web full episode podcast")
        self.assertEqual(res_ep.items[0].audio_preview_url, "https://p.scdn.co/mp3-preview/ep42")

    def test_rejects_20_to_30_second_snippets_and_picks_full_song(self):
        item = spotify.SpotifyItem(title="Midnight Signal", artist="Synth Collective", duration=215, kind="track", index=1)
        candidates = [
            # Rank 1: 28-second YouTube Short / TikTok teaser (previously picked by ytsearch1!)
            {"title": "Synth Collective - Midnight Signal #shorts", "channel": "Synth", "duration": 28, "webpage_url": "https://youtube.com/shorts/abc"},
            # Rank 2: 30-second audio preview snippet
            {"title": "Midnight Signal (30 sec preview)", "channel": "Promo", "duration": 30, "webpage_url": "https://youtube.com/watch?v=prev"},
            # Rank 3: Full 215-second official track on Topic channel
            {"title": "Midnight Signal", "channel": "Synth Collective - Topic", "duration": 215, "webpage_url": "https://youtube.com/watch?v=fullsong"},
            # Rank 4: 1-hour extended loop
            {"title": "Midnight Signal (1 Hour Loop)", "channel": "Loops", "duration": 3600, "webpage_url": "https://youtube.com/watch?v=loop"},
        ]
        chosen = spotify.pick_best_candidate(candidates, item)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["webpage_url"], "https://youtube.com/watch?v=fullsong")
        self.assertLess(spotify.score_candidate(candidates[0], item), 0)
        self.assertLess(spotify.score_candidate(candidates[1], item), 0)

        # Verify Spotify 29.7s embed preview durations are sanitized to None so we don't target 30s clips
        self.assertIsNone(spotify._sanitize_spotify_duration(29700, "track"))
        self.assertIsNone(spotify._sanitize_spotify_duration(30000, "track"))
        self.assertEqual(spotify._sanitize_spotify_duration(215000, "track"), 215)
        # Verify rank_candidates returns ordered list of valid full-length candidates
        ranked = spotify.rank_candidates(candidates, item)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["webpage_url"], "https://youtube.com/watch?v=fullsong")

    def test_two_pass_retry_recovers_failed_tracks(self):
        resolved = spotify.SpotifyResolved(
            url="https://open.spotify.com/playlist/pl1",
            kind="playlist",
            item_id="pl1",
            title="Test Playlist",
            creator="Tester",
            duration=400,
            items=[
                spotify.SpotifyItem("Song One", "Artist A", 200, "track", 1),
                spotify.SpotifyItem("Song Two", "Artist B", 200, "track", 2),
            ],
        )
        calls = []

        def fake_single_download(item, *, pass_num, out_dir, **kwargs):
            calls.append((item.title, pass_num))
            # Song Two fails on Pass 1, then succeeds on Pass 2!
            if item.title == "Song Two" and pass_num == 1:
                return []
            p = os.path.join(out_dir, f"{item.index:02d} - {item.title}.mp3")
            Path(p).write_text("audio", encoding="utf-8")
            return [p]

        orig_single = spotify._download_single_spotify_item
        orig_spotdl = spotify.is_spotdl_installed
        spotify._download_single_spotify_item = fake_single_download
        spotify.is_spotdl_installed = lambda: False
        logs = []
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                files = spotify.download_spotify(
                    resolved,
                    out_dir=tmpdir,
                    max_passes=2,
                    log_cb=lambda msg, lvl: logs.append((msg, lvl)),
                )
                self.assertEqual(len(files), 2)
                # Pass 1 ran both songs; Pass 2 ran ONLY Song Two!
                self.assertEqual(calls, [("Song One", 1), ("Song Two", 1), ("Song Two", 2)])
                self.assertTrue(any("PASS 2: retrying 1 failed song(s)" in m for m, _ in logs))
                self.assertTrue(any("recovered on retry: Artist B - Song Two" in m for m, _ in logs))
        finally:
            spotify._download_single_spotify_item = orig_single
            spotify.is_spotdl_installed = orig_spotdl

    def test_core_scan_and_cli_for_spotify(self):
        fake_resolved = spotify.SpotifyResolved(
            url="https://open.spotify.com/track/123",
            kind="track",
            item_id="123",
            title="Signal Song",
            creator="The Receivers",
            duration=240,
            items=[spotify.SpotifyItem("Signal Song", "The Receivers", 240, "track", 1)],
        )
        orig_resolve = spotify.resolve_spotify
        spotify.resolve_spotify = lambda *a, **k: fake_resolved
        try:
            s = core.scan("https://open.spotify.com/track/123")
            self.assertEqual(s.title, "Signal Song")
            self.assertIn("The Receivers", s.channel)
            self.assertIsNotNone(s.spotify_data)
            self.assertEqual(core.count_playlist_entries("https://open.spotify.com/track/123"), 1)
        finally:
            spotify.resolve_spotify = orig_resolve

        o = core.DownloadOptions(
            "https://open.spotify.com/episode/abc", "o", False, "audio", "mp3", "192",
            None, None, False, None, None,
        )
        cli = core.build_cli_command(o)
        self.assertIn("spotify:episode", cli)




class MultiPlatformSupport(unittest.TestCase):
    def test_youtube_url_detection(self):
        cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", ("youtube", "video", "dQw4w9WgXcQ", True)),
            ("https://youtu.be/dQw4w9WgXcQ", ("youtube", "video", "dQw4w9WgXcQ", True)),
            ("https://www.youtube.com/shorts/abc123XYZ", ("youtube", "short", "abc123XYZ", True)),
            ("https://www.youtube.com/playlist?list=PL123456789", ("youtube", "playlist", "PL123456789", True)),
            ("https://www.youtube.com/", ("youtube", "unsupported", "", False)),
        ]
        for url, want in cases:
            d = platforms.detect_platform(url)
            self.assertEqual((d.platform, d.kind, d.item_id, d.supported), want, url)

    def test_instagram_url_detection_and_cookie_requirements(self):
        cases = [
            ("https://www.instagram.com/reel/C8abc123_/", ("instagram", "reel", "C8abc123_", True, False)),
            ("https://instagram.com/p/C9xyz987/", ("instagram", "post", "C9xyz987", True, False)),
            ("https://www.instagram.com/tv/C7igtv00/", ("instagram", "igtv", "C7igtv00", True, False)),
            ("https://www.instagram.com/stories/openband/33445566/", ("instagram", "story", "33445566", True, True)),
            ("https://www.instagram.com/explore/", ("instagram", "unsupported", "", False, False)),
            ("https://www.instagram.com/openband_official/", ("instagram", "unsupported", "openband_official", False, False)),
        ]
        for url, (plat, kind, item_id, sup, req_cookie) in cases:
            d = platforms.detect_platform(url)
            self.assertEqual((d.platform, d.kind, d.item_id, d.supported, d.requires_cookies),
                             (plat, kind, item_id, sup, req_cookie), url)

    def test_twitter_x_url_detection_and_normalization(self):
        cases = [
            ("https://x.com/openband/status/18450011223344", ("twitter", "status", "18450011223344", True)),
            ("https://twitter.com/openband/status/18450011223344?s=20", ("twitter", "status", "18450011223344", True)),
            ("https://vxtwitter.com/openband/status/18450011223344", ("twitter", "status", "18450011223344", True)),
            ("https://fxtwitter.com/openband/status/18450011223344", ("twitter", "status", "18450011223344", True)),
            ("https://x.com/i/spaces/1vAxRopQwZKl", ("twitter", "space", "1vAxRopQwZKl", True)),
            ("https://x.com/i/broadcasts/1OdKrBpQwZKl", ("twitter", "broadcast", "1OdKrBpQwZKl", True)),
            ("https://t.co/AbCdEf123", ("twitter", "shortlink", "AbCdEf123", True)),
            ("https://x.com/home", ("twitter", "unsupported", "", False)),
            ("https://x.com/openband_user", ("twitter", "unsupported", "openband_user", False)),
        ]
        for url, want in cases:
            d = platforms.detect_platform(url)
            self.assertEqual((d.platform, d.kind, d.item_id, d.supported), want, url)
        # Verify vxtwitter/fxtwitter canonicalizes to x.com
        d_vx = platforms.detect_platform("https://vxtwitter.com/openband/status/18450011223344")
        self.assertTrue(d_vx.canonical_url.startswith("https://x.com/"))

    def test_facebook_url_detection(self):
        cases = [
            ("https://www.facebook.com/watch/?v=987654321", ("facebook", "watch", "987654321", True, False)),
            ("https://fb.watch/rTyUiOp12/", ("facebook", "watch", "rTyUiOp12", True, False)),
            ("https://www.facebook.com/reel/1122334455", ("facebook", "reel", "1122334455", True, False)),
            ("https://www.facebook.com/openband/videos/5566778899/", ("facebook", "video", "5566778899", True, False)),
            ("https://www.facebook.com/share/v/AbCdEfGh12/", ("facebook", "video", "AbCdEfGh12", True, False)),
            ("https://www.facebook.com/share/r/ReElId99/", ("facebook", "reel", "ReElId99", True, False)),
            ("https://www.facebook.com/stories/123456789/", ("facebook", "story", "123456789", True, True)),
            ("https://www.facebook.com/", ("facebook", "unsupported", "", False, False)),
        ]
        for url, (plat, kind, item_id, sup, req_cookie) in cases:
            d = platforms.detect_platform(url)
            self.assertEqual((d.platform, d.kind, d.item_id, d.supported, d.requires_cookies),
                             (plat, kind, item_id, sup, req_cookie), url)

    def test_social_scan_metadata_and_format_fallbacks(self):
        # 1. Instagram Reel scan with creator handle and muxed MP4
        ig_info = {
            "title": "Behind the scenes at the archive",
            "uploader": "OpenBand Collective",
            "uploader_id": "openband.collective",
            "duration": 42,
            "upload_date": "20261012",
            "webpage_url": "https://www.instagram.com/reel/C8abc123_/",
            "formats": [
                {"format_id": "dash-hd", "vcodec": "avc1.64001f", "acodec": "mp4a.40.2", "height": 1080, "fps": 30, "ext": "mp4", "tbr": 2500},
                {"format_id": "dash-sd", "vcodec": "avc1.4d401e", "acodec": "mp4a.40.2", "height": 720, "fps": 30, "ext": "mp4", "tbr": 1200},
            ],
        }
        # 2. Facebook video where vcodec/height are omitted on direct SD/HD MP4 formats
        fb_info = {
            "title": "Community Town Hall Stream",
            "uploader": "Free Media Commons",
            "duration": 180,
            "webpage_url": "https://www.facebook.com/watch/?v=987654321",
            "formats": [
                {"format_id": "hd", "ext": "mp4", "tbr": 1800, "acodec": "mp4a.40.2"},
                {"format_id": "sd", "ext": "mp4", "tbr": 800, "acodec": "mp4a.40.2"},
            ],
        }
        orig_extract = core._extract
        try:
            core._extract = lambda *a, **k: ig_info
            s_ig = core.scan("https://www.instagram.com/reel/C8abc123_/")
            self.assertEqual(s_ig.platform, "instagram")
            self.assertEqual(s_ig.media_kind, "reel")
            self.assertEqual(s_ig.channel, "OpenBand Collective (@openband.collective)")
            self.assertEqual(s_ig.heights, [1080, 720])
            self.assertTrue(s_ig.rows[0].has_audio)
            self.assertEqual(s_ig.webpage_url, "https://www.instagram.com/reel/C8abc123_/")

            core._extract = lambda *a, **k: fb_info
            s_fb = core.scan("https://www.facebook.com/watch/?v=987654321")
            self.assertEqual(s_fb.platform, "facebook")
            self.assertEqual(s_fb.heights, [720, 480])
            self.assertEqual(s_fb.rows[0].codec, "h264")
        finally:
            core._extract = orig_extract

    def test_failure_cases_unsupported_image_only_and_drm(self):
        # 1. Unsupported bare profile URL fails immediately without calling _extract
        with self.assertRaises(ValueError) as ctx:
            core.scan("https://www.instagram.com/openband_official/")
        self.assertIn("profile links", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx_x:
            core.scan("https://x.com/openband_user")
        self.assertIn("profile links", str(ctx_x.exception))

        # 2. Image-only or text-only social post fails with clear message
        orig_extract = core._extract
        try:
            core._extract = lambda *a, **k: {"title": "Text only tweet", "formats": []}
            with self.assertRaises(RuntimeError) as ctx_empty:
                core.scan("https://x.com/openband/status/18450011223344")
            self.assertIn("image-only or text-only", str(ctx_empty.exception))

            # 3. DRM-protected media is refused explicitly
            core._extract = lambda *a, **k: {"title": "DRM Stream", "drm": True, "formats": []}
            with self.assertRaises(RuntimeError) as ctx_drm:
                core.scan("https://www.youtube.com/watch?v=drm12345")
            self.assertIn("DRM-protected", str(ctx_drm.exception))
        finally:
            core._extract = orig_extract

    def test_platform_friendly_errors_and_secret_redaction(self):
        err_cases = {
            "ERROR: [Instagram] C8abc: Requested content is not available, rate-limit reached or login_required": "Instagram requires authentication",
            "ERROR: [twitter] 1845: No video could be found in this tweet": "No video or audio stream",
            "ERROR: [twitter] 1845: NSFW tweet requires login": "X (Twitter) restricted access",
            "ERROR: [facebook] 9876: This video is only available to friends": "Facebook requires login",
            "ERROR: This video is DRM protected (Widevine)": "DRM-protected",
            "ERROR: HTTP Error 404: Not Found": "404",
        }
        for raw, expected in err_cases.items():
            f = core.friendly_error(raw)
            self.assertIn(expected.lower(), (f.headline + " " + f.hint).lower(), raw)

        # Verify session cookies & tokens are redacted from logs
        dirty = "Cookie: sessionid=abcdef123456789; auth_token=9876543210abcdef; ct0=xyz987654321"
        cleaned = core.clean(dirty)
        self.assertNotIn("abcdef123456789", cleaned)
        self.assertNotIn("9876543210abcdef", cleaned)
        self.assertIn("[REDACTED]", cleaned)

        # Verify field guide lessons for Instagram, X, and Facebook URLs
        self.assertIn("INSTAGRAM", kb.learn("url", "https://www.instagram.com/reel/C8abc/").title)
        self.assertIn("X (TWITTER)", kb.learn("url", "https://x.com/user/status/123").title)
        self.assertIn("FACEBOOK", kb.learn("url", "https://fb.watch/abc/").title)




class BatchAndStewardship(unittest.TestCase):
    def test_parse_batch_urls_and_load_file(self):
        raw_input = """
        # OpenBand reading & listening list
        https://www.youtube.com/watch?v=dQw4w9WgXcQ
        - [Reel](https://www.instagram.com/reel/C8abc123_/)
        https://x.com/openband/status/18450011223344  # inline comment
        spotify:track:4uLU6hMCjMI75M1A2tKUQC
        https://www.youtube.com/watch?v=dQw4w9WgXcQ
        """
        urls = core.parse_batch_urls(raw_input)
        self.assertEqual(
            urls,
            [
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://www.instagram.com/reel/C8abc123_/",
                "https://x.com/openband/status/18450011223344",
                "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            bfile = Path(tmpdir) / "urls.txt"
            bfile.write_text(raw_input, encoding="utf-8")
            loaded = core.load_batch_file(bfile)
            self.assertEqual(loaded, urls)

    def test_catalog_exports_m3u8_markdown_and_csv(self):
        entries = [
            core.CatalogEntry(
                title="Open Signal Documentary",
                channel="Commons Collective",
                url="https://www.youtube.com/watch?v=doc123",
                spec="YOUTUBE · H.264 · 1080p · MP4",
                size=150_000_000,
                path="/tmp/Open Signal Documentary.mp4",
                archived_at="2026-10-25 10:00",
            ),
            core.CatalogEntry(
                title="Midnight Signal",
                channel="Synth Collective",
                url="https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
                spec="SPOTIFY · MP3 · 320 kbps",
                size=8_500_000,
                path="/tmp/Midnight Signal.mp3",
                archived_at="2026-10-25 10:05",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            m3u_path = Path(tmpdir) / "catalog.m3u8"
            md_path = Path(tmpdir) / "catalog.md"
            csv_path = Path(tmpdir) / "catalog.csv"

            core.export_catalog_m3u8(entries, m3u_path)
            core.export_catalog_markdown(entries, md_path)
            core.export_catalog_csv(entries, csv_path)

            m3u_txt = m3u_path.read_text(encoding="utf-8")
            self.assertIn("#EXTM3U", m3u_txt)
            self.assertIn("#EXTINF:-1,Commons Collective - Open Signal Documentary", m3u_txt)
            self.assertIn("/tmp/Open Signal Documentary.mp4", m3u_txt)

            md_txt = md_path.read_text(encoding="utf-8")
            self.assertIn("OPENBAND · LOCAL COMMONS CATALOG", md_txt)
            self.assertIn("Open Signal Documentary", md_txt)
            self.assertIn("Midnight Signal", md_txt)

            csv_txt = csv_path.read_text(encoding="utf-8")
            self.assertIn("archived_at,title,creator,spec,size_bytes,path,source_url", csv_txt)
            self.assertIn("Open Signal Documentary", csv_txt)

    def test_provenance_nfo_and_transcript_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_file = Path(tmpdir) / "Lecture_01.mp4"
            media_file.write_text("video", encoding="utf-8")
            nfo_path = core.write_provenance_nfo(
                str(media_file),
                title="Lecture 01: The Open Web",
                creator="OpenBand University (@openband)",
                source_url="https://www.youtube.com/watch?v=lec01",
                platform="youtube",
                spec="YOUTUBE · H.264 · 1080p",
                upload_date="2026-10-20",
                description="A lecture on digital preservation & media stewardship.",
            )
            self.assertIsNotNone(nfo_path)
            self.assertTrue(nfo_path.is_file())
            nfo_xml = nfo_path.read_text(encoding="utf-8")
            self.assertIn("<title>Lecture 01: The Open Web</title>", nfo_xml)
            self.assertIn("<artist>OpenBand University (@openband)</artist>", nfo_xml)
            self.assertIn("https://www.youtube.com/watch?v=lec01", nfo_xml)

            # Create a matching .vtt file and verify find_transcript_for_media auto-generates & finds .transcript.txt
            vtt_file = Path(tmpdir) / "Lecture_01.en.vtt"
            vtt_file.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nPreservation matters.\n", encoding="utf-8")
            tx_found = core.find_transcript_for_media(str(media_file))
            self.assertIsNotNone(tx_found)
            self.assertTrue(tx_found.name.endswith(".transcript.txt"))
            self.assertIn("Preservation matters.", tx_found.read_text(encoding="utf-8"))


    def test_obfuscated_carrier_easter_egg_and_no_plaintext_leak(self):
        import base64
        # Construct test triggers from base64 so even the test file never contains plaintext triggers
        b64_triggers = [
            b"b3BlbmJhbmQ6Ly9tYW5pZmVzdG8=",
            b"b3BlbmJhbmQ6Ly9sZXR0ZXI=",
            b"aHR0cHM6Ly9vcGVuYmFuZC5vcmcvbWFuaWZlc3Rv",
            b"YWJvdXQ6bWFuaWZlc3Rv",
            b"c2lnbmFsOi8vb3BlbmJhbmQ=",
        ]
        for b64_t in b64_triggers:
            trig = base64.b64decode(b64_t).decode("utf-8")
            self.assertTrue(platforms.is_manifesto_easter_egg(trig))
            det = platforms.detect_platform(trig)
            self.assertEqual((det.platform, det.kind, det.supported), ("openband", "carrier", True))
            lesson = kb.learn("url", trig)
            self.assertIn("CARRIER 00", lesson.title)

        # Audit every source file in the repository to verify the Easter Egg text & trigger URIs are NOT visible in code
        root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        forbidden_plaintext = [
            base64.b64decode(b"QSBMRVRURVIgRk9SIEZSRUUgTUVESUE=").decode("utf-8"),
            base64.b64decode(b"RGVhciBsaXN0ZW5lciwgdmlld2Vy").decode("utf-8"),
            base64.b64decode(b"b3BlbmJhbmQ6Ly9tYW5pZmVzdG8=").decode("utf-8"),
            base64.b64decode(b"cmVudGluZyBvdXIgY3VsdHVyZQ==").decode("utf-8"),
        ]
        for py_file in list(root.glob("*.py")) + list((root / "ytdl").glob("*.py")) + [root / "README.md"]:
            source_text = py_file.read_text(encoding="utf-8")
            for secret in forbidden_plaintext:
                self.assertNotIn(secret, source_text, f"Plaintext leak {secret!r} found in {py_file.name}")

    def test_packaging_and_readme_files_present(self):
        root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pyproject = root / "pyproject.toml"
        readme = root / "README.md"
        self.assertTrue(pyproject.is_file())
        self.assertTrue(readme.is_file())
        self.assertIn('openband = "ytdl.app:main"', pyproject.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
