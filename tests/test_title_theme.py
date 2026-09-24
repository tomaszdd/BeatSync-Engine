#!/usr/bin/env python3
"""Unit tests for AI mood-matched title typography, presets, and themed transitions."""

import os
import sys
import unittest
import unittest.mock

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from title_theme import (
    THEME_AUTO,
    THEME_WARM_SENTIMENTAL,
    THEME_JOYFUL_BRIGHT,
    THEME_UPBEAT_ENERGETIC,
    THEME_PRESETS,
    compute_mood_signature,
    resolve_theme,
)
from ffmpeg_processing import _build_transition_filtergraph


class TestTitleTheme(unittest.TestCase):
    def test_bundled_font_assets_exist(self):
        for theme_name, preset in THEME_PRESETS.items():
            self.assertTrue(
                os.path.isfile(preset.title_font),
                f"Missing title font for {theme_name}: {preset.title_font}",
            )
            self.assertTrue(
                os.path.isfile(preset.subtitle_font),
                f"Missing subtitle font for {theme_name}: {preset.subtitle_font}",
            )

    def test_compute_mood_signature_warm_sentimental(self):
        # Newborn/family clips: dominant soft, beauty, flow; moderate/low energy
        clips = [
            {"tags": ["soft", "beauty"]},
            {"tags": ["soft", "flow"]},
            {"tags": ["beauty", "clean"]},
            {"tags": ["soft"]},
        ]
        beat_info = {
            "audio_visual_profile": {
                "average_wave": 0.42,
                "average_rhythm": 0.45,
                "average_impact": 0.40,
            },
            "sections": [{"type": "intro"}, {"type": "verse"}],
        }
        sig = compute_mood_signature(clips, beat_info)
        self.assertEqual(sig.selected_theme, THEME_WARM_SENTIMENTAL)
        self.assertGreater(sig.warmth, 0.4)
        self.assertLess(sig.energy, 0.6)
        self.assertEqual(sig.dominant_emotion, "soft")

    def test_compute_mood_signature_upbeat_energetic(self):
        # Action/GoPro clips: dominant hype, tension, action; high energy
        clips = [
            {"tags": ["hype", "action"]},
            {"tags": ["hype", "drop"]},
            {"tags": ["tension", "action"]},
            {"tags": ["hype"]},
        ]
        beat_info = {
            "audio_visual_profile": {
                "average_wave": 0.78,
                "average_rhythm": 0.82,
                "average_impact": 0.75,
            },
            "sections": [{"type": "chorus"}, {"type": "finale"}],
        }
        sig = compute_mood_signature(clips, beat_info)
        self.assertEqual(sig.selected_theme, THEME_UPBEAT_ENERGETIC)
        self.assertGreaterEqual(sig.energy, 0.58)

    def test_compute_mood_signature_joyful_bright(self):
        # Upbeat/celebratory clips: neutral/clean, moderate energy
        clips = [
            {"tags": ["neutral", "clean"]},
            {"tags": ["clean"]},
            {"tags": ["neutral"]},
        ]
        beat_info = {
            "audio_visual_profile": {
                "average_wave": 0.55,
                "average_rhythm": 0.60,
                "average_impact": 0.50,
            },
            "sections": [{"type": "verse"}],
        }
        sig = compute_mood_signature(clips, beat_info)
        self.assertEqual(sig.selected_theme, THEME_JOYFUL_BRIGHT)

    def test_compute_mood_signature_empty_fallback(self):
        sig = compute_mood_signature([], {})
        self.assertIn(sig.selected_theme, THEME_PRESETS)
        self.assertIsNotNone(sig.reason)

    def test_resolve_theme_auto_vs_manual(self):
        # Warm input data
        clips = [{"tags": ["soft", "beauty"]}]
        beat_info = {"audio_visual_profile": {"average_wave": 0.3, "average_rhythm": 0.3}}

        # Auto should pick Warm & Sentimental
        preset_auto, sig_auto = resolve_theme(THEME_AUTO, clips, beat_info)
        self.assertEqual(preset_auto.name, THEME_WARM_SENTIMENTAL)
        self.assertEqual(sig_auto.selected_theme, THEME_WARM_SENTIMENTAL)

        # Force Upbeat & Energetic override
        preset_override, sig_override = resolve_theme(THEME_UPBEAT_ENERGETIC, clips, beat_info)
        self.assertEqual(preset_override.name, THEME_UPBEAT_ENERGETIC)
        self.assertEqual(sig_override.selected_theme, THEME_UPBEAT_ENERGETIC)
        self.assertIn("Manual override", sig_override.reason)

        # Force Joyful & Bright override
        preset_jb, sig_jb = resolve_theme(THEME_JOYFUL_BRIGHT, clips, beat_info)
        self.assertEqual(preset_jb.name, THEME_JOYFUL_BRIGHT)

    def test_filtergraph_with_theme_transition_tint(self):
        video_files = ["clip0.mp4", "clip1.mp4"]
        transitions = [0.4]
        durations = [2.0, 3.0]
        preset = THEME_PRESETS[THEME_WARM_SENTIMENTAL]

        input_args, filter_str = _build_transition_filtergraph(
            video_files,
            transitions,
            durations,
            theme_preset=preset,
        )
        self.assertIn("xfade=transition=fade", filter_str)
        # Should include timeline-enabled eq tint for the transition window
        self.assertIn("eq=", filter_str)
        self.assertIn("enable='between(t,", filter_str)
        self.assertIn(preset.transition_tint_eq, filter_str)

    def test_filtergraph_without_theme_transition_tint(self):
        video_files = ["clip0.mp4", "clip1.mp4"]
        transitions = [0.4]
        durations = [2.0, 3.0]

        input_args, filter_str = _build_transition_filtergraph(
            video_files,
            transitions,
            durations,
            theme_preset=None,
        )
        self.assertIn("xfade=transition=fade", filter_str)
        # Without preset, no eq tint should be injected
        self.assertNotIn("eq=", filter_str)

    @unittest.mock.patch("ffmpeg_processing._run_media_command")
    @unittest.mock.patch("ffmpeg_processing.os.replace")
    @unittest.mock.patch("ffmpeg_processing.get_video_resolution", return_value=(1920, 1080))
    @unittest.mock.patch("ffmpeg_processing.get_video_duration", return_value=60.0)
    @unittest.mock.patch("ffmpeg_processing.get_video_fps", return_value=30.0)
    def test_title_card_blend_order_prevents_leak(self, mock_fps, mock_dur, mock_res, mock_replace, mock_run):
        from ffmpeg_processing import add_text_overlays_ffmpeg
        from title_theme import ThemePreset
        mock_run.return_value = unittest.mock.MagicMock(returncode=0, stderr="")

        # 1. With graphic overlay (e.g. Warm & Sentimental)
        preset_warm = THEME_PRESETS[THEME_WARM_SENTIMENTAL]
        add_text_overlays_ffmpeg(
            "dummy_video.mp4",
            start_text="Teresa S. Dunn\n1st October 2025",
            title_card_enabled=True,
            theme_preset=preset_warm,
        )
        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        fc_idx = cmd.index("-filter_complex")
        fc_str = cmd[fc_idx + 1]

        # Verify blend input order: [orig] must be first (input 0), [themed_bg] second (input 1)
        self.assertIn("[orig][themed_bg]blend=all_expr=", fc_str)
        self.assertNotIn("[themed_bg][orig]blend=", fc_str)

        # Verify blend expression semantics:
        # At start (T <= t_hold), output B (themed_bg)
        # At resolve (T >= window), output A (orig)
        # Bypass (t > window) passes input 0 unchanged -> orig (sharp)
        self.assertRegex(fc_str, r"if\(lte\(T,[\d\.]+\),B,")
        self.assertRegex(fc_str, r"if\(gte\(T,[\d\.]+\),A,")

        # 2. Without graphic overlay
        import dataclasses
        preset_no_graphic = dataclasses.replace(preset_warm, graphic_overlay_type=None)
        mock_run.reset_mock()
        add_text_overlays_ffmpeg(
            "dummy_video.mp4",
            start_text="Teresa S. Dunn\n1st October 2025",
            title_card_enabled=True,
            theme_preset=preset_no_graphic,
        )
        self.assertTrue(mock_run.called)
        cmd2 = mock_run.call_args[0][0]
        fc_str2 = cmd2[cmd2.index("-filter_complex") + 1]

        # Verify blend input order without graphic: [orig][blurred]
        self.assertIn("[orig][blurred]blend=all_expr=", fc_str2)
        self.assertNotIn("[blurred][orig]blend=", fc_str2)
        self.assertRegex(fc_str2, r"if\(lte\(T,[\d\.]+\),B,")
        self.assertRegex(fc_str2, r"if\(gte\(T,[\d\.]+\),A,")


if __name__ == "__main__":
    unittest.main()

