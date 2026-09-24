#!/usr/bin/env python3
"""Unit tests for Ident Outro append and Watermark options."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

# Add src to sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from paths import (
    get_ident_asset_path,
    get_watermark_asset_path,
    DEFAULT_IDENT_ASSET_PATH,
    DEFAULT_WATERMARK_ASSET_PATH,
)
from ffmpeg_processing import (
    compute_watermark_layout,
    build_fit_scale_filter,
    add_text_overlays_ffmpeg,
    append_ident_outro,
)
from clip_plan import build_render_plan, PLAN_VERSION
from ui_content import (
    LABEL_IDENT_OUTRO_ENABLED,
    INFO_IDENT_OUTRO_ENABLED,
    LABEL_WATERMARK_ENABLED,
    INFO_WATERMARK_ENABLED,
)
try:
    if 'gradio' not in sys.modules:
        sys.modules['gradio'] = MagicMock()
    from gui import _default_settings_state, _SETTINGS_KEYS
except Exception:
    _default_settings_state = None
    _SETTINGS_KEYS = None


class TestIdentOutroWatermark(unittest.TestCase):
    """Test suite for Ident Outro and Watermark features."""

    def test_default_paths(self):
        """Verify default asset paths and getters."""
        ident_path = get_ident_asset_path()
        self.assertIn("TDD_Intro_3D_1.mov", ident_path)

        wm_path = get_watermark_asset_path()
        self.assertTrue(wm_path.endswith(os.path.join("assets", "tdd_watermark.png")))
        self.assertTrue(os.path.isfile(wm_path), f"Default watermark asset missing at {wm_path}")

        # Check default watermark image properties
        with Image.open(wm_path) as im:
            self.assertEqual(im.mode, 'RGBA')
            self.assertGreater(im.width, 0)
            self.assertGreater(im.height, 0)

    def test_watermark_layout_landscape_4k(self):
        """Test watermark layout on 4K landscape (3840x2160)."""
        wm_w, wm_h, x, y = compute_watermark_layout(3840, 2160, 889, 676, position='bottom_right')
        # 8.5% of 3840 = 326.4 -> 326 px width
        self.assertTrue(320 <= wm_w <= 335, f"Expected ~326, got {wm_w}")
        self.assertEqual(wm_w % 2, 0, "Watermark width must be even")
        self.assertEqual(wm_h % 2, 0, "Watermark height must be even")
        self.assertEqual(x % 2, 0, "Watermark X must be even")
        self.assertEqual(y % 2, 0, "Watermark Y must be even")
        # Ensure inside frame bounds
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + wm_w, 3840)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + wm_h, 2160)
        # Check bottom-right placement
        self.assertGreater(x, 3000)
        self.assertGreater(y, 1600)

    def test_watermark_layout_vertical_9_16(self):
        """Test watermark layout on 1080x1920 vertical format."""
        wm_w, wm_h, x, y = compute_watermark_layout(1080, 1920, 889, 676, position='bottom_right')
        # 10% of 1080 = 108 px width
        self.assertEqual(wm_w, 108)
        self.assertEqual(wm_w % 2, 0)
        self.assertEqual(wm_h % 2, 0)
        self.assertEqual(x % 2, 0)
        self.assertEqual(y % 2, 0)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + wm_w, 1080)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + wm_h, 1920)
        # Check bottom-right placement
        self.assertGreater(x, 850)
        self.assertGreater(y, 1600)

    def test_watermark_layout_positions(self):
        """Test top-left, top-right, bottom-left, top-center, bottom-center placements."""
        w, h = 1920, 1080
        for pos in ['top_left', 'top_right', 'bottom_left', 'top_center', 'bottom_center']:
            wm_w, wm_h, x, y = compute_watermark_layout(w, h, 400, 300, position=pos)
            self.assertEqual(wm_w % 2, 0)
            self.assertEqual(wm_h % 2, 0)
            self.assertEqual(x % 2, 0)
            self.assertEqual(y % 2, 0)
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + wm_w, w)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(y + wm_h, h)

    def test_fit_scale_filter_letterbox(self):
        """Test build_fit_scale_filter creates proper letterboxing without stretch."""
        f_land = build_fit_scale_filter(3840, 2160)
        self.assertIn("scale=3840:2160:force_original_aspect_ratio=decrease", f_land)
        self.assertIn("pad=3840:2160:", f_land)
        self.assertIn("setsar=1", f_land)

        f_vert = build_fit_scale_filter(1080, 1920)
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=decrease", f_vert)
        self.assertIn("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black", f_vert)

    @patch("ffmpeg_processing._run_media_command")
    @patch("ffmpeg_processing.get_video_duration", return_value=10.0)
    @patch("ffmpeg_processing.get_video_resolution", return_value=(3840, 2160))
    def test_watermark_filter_graph_input_ordering(self, mock_res, mock_dur, mock_run):
        """Verify video is Input 0, watermark PNG is Input 1, and shortest=1 is set."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        with patch("os.replace") as mock_replace:
            add_text_overlays_ffmpeg(
                "dummy_video.mp4",
                watermark_enabled=True,
                watermark_opacity=0.60,
                watermark_position="bottom_right"
            )

        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        # Check input ordering in cmd
        self.assertEqual(cmd[cmd.index("-i") + 1], "dummy_video.mp4")
        # Check watermark input exists with -loop 1
        loop_idx = cmd.index("-loop")
        self.assertEqual(cmd[loop_idx + 1], "1")
        # Check filter_complex string
        fc_idx = cmd.index("-filter_complex")
        fc_str = cmd[fc_idx + 1]

        # Video stream MUST be Input 0: [0:v]
        self.assertIn("[0:v]", fc_str)
        # Watermark MUST be scaled from Input 1: [1:v]scale=
        self.assertIn("[1:v]scale=", fc_str)
        # Overlay MUST take video as first arg and watermark as second: [v_txt][wm_mark]overlay=...
        self.assertIn("[wm_mark]overlay=", fc_str)
        self.assertIn(":shortest=1", fc_str)
        # Opacity colorchannelmixer
        self.assertIn("colorchannelmixer=aa=0.60", fc_str)

    def test_render_plan_serialization(self):
        """Verify build_render_plan serializes ident_outro and watermark options."""
        plan = build_render_plan(
            output_file="/tmp/test_out.mp4",
            audio_file="/tmp/test_audio.mp3",
            video_files=["/tmp/v1.mp4"],
            beat_times=[0.0, 1.0, 2.0],
            segment_durations=[1.0, 1.0],
            clips=[{"video_file": "/tmp/v1.mp4", "start_time": 0.0}],
            fps=30.0,
            target_resolution=(3840, 2160),
            ident_outro_enabled=True,
            ident_clip_path="D:\\BeatSync-Assets\\TDD_Intro_3D_1.mov",
            watermark_enabled=True,
            watermark_image="/path/to/custom_watermark.png",
        )
        self.assertTrue(plan["ident_outro_enabled"])
        self.assertEqual(plan["ident_clip_path"], "D:\\BeatSync-Assets\\TDD_Intro_3D_1.mov")
        self.assertTrue(plan["watermark_enabled"])
        self.assertEqual(plan["watermark_image"], "/path/to/custom_watermark.png")

    def test_gui_settings_state_and_keys(self):
        """Verify GUI persistence defaults and keys contain new options in matching order."""
        if _default_settings_state is None or _SETTINGS_KEYS is None:
            self.skipTest("GUI imports skipped")

        defaults = _default_settings_state()
        self.assertIn("ident_outro_enabled", defaults)
        self.assertIn("watermark_enabled", defaults)
        self.assertFalse(defaults["ident_outro_enabled"])
        self.assertFalse(defaults["watermark_enabled"])

        self.assertIn("ident_outro_enabled", _SETTINGS_KEYS)
        self.assertIn("watermark_enabled", _SETTINGS_KEYS)

        # Confirm placement right after transitions_enabled
        trans_idx = _SETTINGS_KEYS.index("transitions_enabled")
        self.assertEqual(_SETTINGS_KEYS[trans_idx + 1], "ident_outro_enabled")
        self.assertEqual(_SETTINGS_KEYS[trans_idx + 2], "watermark_enabled")


if __name__ == "__main__":
    unittest.main()
