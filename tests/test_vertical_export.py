#!/usr/bin/env python3
"""Unit tests for Vertical (9:16) export mode and smart crop-to-fill."""

import os
import sys
import unittest
import tempfile
import numpy as np
from PIL import Image

# Add src to sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ffmpeg_processing import build_crop_to_fill_filter, build_fit_scale_filter, _title_font_size
from subject_detection import detect_subject, detect_subject_bbox, score_subject_and_bbox
from title_theme import (
    THEME_AUTO,
    THEME_WARM_SENTIMENTAL,
    THEME_JOYFUL_BRIGHT,
    THEME_UPBEAT_ENERGETIC,
    THEME_PRESETS,
    _compute_text_layout,
    render_decorative_motif,
)
from clip_plan import build_render_plan, PLAN_VERSION
from ui_content import (
    ORIENTATION_LANDSCAPE,
    ORIENTATION_VERTICAL,
    ORIENTATION_CHOICES,
    LABEL_EXPORT_ORIENTATION,
)
try:
    from gui import _default_settings_state, _SETTINGS_KEYS
except ImportError:
    _default_settings_state = None
    _SETTINGS_KEYS = None


class TestVerticalExport(unittest.TestCase):
    """Test suite for vertical export mode and smart crop-to-fill."""

    def test_build_crop_to_fill_filter_4k_center_fallback(self):
        """Test 4K landscape to 9:16 vertical with no bbox falls back to geometric center."""
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=None)
        # 3840 * 1920 / 2160 = 3413.33 -> scaled to 3414:1920
        # Geometric center cx=0.5 -> center_x = 1707 -> crop_x = 1707 - 540 = 1167 -> 1166 or 1168
        self.assertIn("scale=3414:1920", filter_str)
        self.assertIn("crop=1080:1920:", filter_str)
        self.assertIn(":0,setsar=1", filter_str)
        # Parse crop_x
        parts = filter_str.split("crop=")[1].split(",")[0].split(":")
        w, h, crop_x, crop_y = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)
        self.assertEqual(crop_y, 0)
        self.assertTrue(1160 <= crop_x <= 1170)
        self.assertEqual(crop_x % 2, 0, "crop_x must be even")

    def test_build_crop_to_fill_filter_4k_subject_centered(self):
        """Test 4K landscape to 9:16 vertical centered on detected subject bbox."""
        # Subject centered at cx = 0.363 (e.g. x0=0.20, x1=0.526)
        bbox = (0.20, 0.1, 0.526, 0.9)
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        parts = filter_str.split("crop=")[1].split(",")[0].split(":")
        crop_x = int(parts[2])
        # cx = 0.363 * 3414 = 1239.3 -> crop_x = 1239.3 - 540 = 699.3 -> 698 or 700
        self.assertTrue(690 <= crop_x <= 710, f"Expected crop_x ~698, got {crop_x}")
        self.assertEqual(crop_x % 2, 0, "crop_x must be even")

    def test_build_crop_to_fill_filter_clamping_left_edge(self):
        """Test subject on far left of 4K frame clamps crop window to 0."""
        bbox = (0.01, 0.1, 0.09, 0.9)  # cx = 0.05
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        parts = filter_str.split("crop=")[1].split(",")[0].split(":")
        crop_x = int(parts[2])
        self.assertEqual(crop_x, 0, "Far-left subject must clamp crop_x to 0")

    def test_build_crop_to_fill_filter_clamping_right_edge(self):
        """Test subject on far right of 4K frame clamps crop window to max_x."""
        bbox = (0.91, 0.1, 0.99, 0.9)  # cx = 0.95
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        parts = filter_str.split("crop=")[1].split(",")[0].split(":")
        crop_x = int(parts[2])
        max_x = 3414 - 1080  # 2334
        self.assertEqual(crop_x, max_x, f"Far-right subject must clamp crop_x to {max_x}")

    def test_build_crop_to_fill_filter_1080p_source(self):
        """Test 1080p (1920x1080) landscape footage scaled to 1080x1920."""
        filter_str = build_crop_to_fill_filter(1920, 1080, 1080, 1920, subject_bbox=None)
        self.assertIn("scale=3414:1920", filter_str)
        self.assertIn("crop=1080:1920:", filter_str)

    def test_build_crop_to_fill_filter_native_vertical_source(self):
        """Test already vertical source (1080x1920) needs 0 crop offset."""
        filter_str = build_crop_to_fill_filter(1080, 1920, 1080, 1920, subject_bbox=(0.2, 0.2, 0.8, 0.8))
        self.assertIn("scale=1080:1920", filter_str)
        self.assertIn("crop=1080:1920:0:0", filter_str)

    def test_landscape_letterbox_behavior_unchanged(self):
        """Confirm existing build_fit_scale_filter retains letterbox/pad for landscape export."""
        ls_filter = build_fit_scale_filter(1920, 1080)
        self.assertIn("force_original_aspect_ratio=decrease", ls_filter)
        self.assertIn("pad=1920:1080", ls_filter)

    def test_title_typography_and_layout_1080x1920(self):
        """Test title card text layout math for 1080x1920 vertical canvas across all themes."""
        title_text = "Teresa S. Dunn"
        sub_text = "1st October 2025"

        for theme_name in [THEME_WARM_SENTIMENTAL, THEME_JOYFUL_BRIGHT, THEME_UPBEAT_ENERGETIC]:
            preset = THEME_PRESETS[theme_name]
            layout = _compute_text_layout(preset, 1080, 1920, title_text, sub_text)
            bbox, t_font_size, s_font_size, gap, t_y, s_y = layout
            x0, y0, x1, y1 = bbox

            # Assert positive and valid coordinates
            self.assertGreaterEqual(x0, 0.0)
            self.assertLess(x1, 1080.0)
            self.assertGreaterEqual(y0, 0.0)
            self.assertLess(y1, 1920.0)
            self.assertGreater(x1, x0)
            self.assertGreater(y1, y0)

            # Assert font size is comfortable and fits within width
            self.assertGreaterEqual(t_font_size, 30)
            self.assertLessEqual(t_font_size, 100)
            self.assertGreater(s_font_size, 16)

            # Assert vertically centered roughly around middle of screen
            block_center_y = (y0 + y1) / 2.0
            self.assertTrue(800 <= block_center_y <= 1120, f"Block center {block_center_y} not centered in 1920")

    def test_render_decorative_motifs_1080x1920_all_themes(self):
        """Test rendering vector decorative motifs in 1080x1920 canvas for each theme."""
        title_text = "Teresa S. Dunn"
        sub_text = "1st October 2025"

        with tempfile.TemporaryDirectory() as tmp_dir:
            for theme_name in [THEME_WARM_SENTIMENTAL, THEME_JOYFUL_BRIGHT, THEME_UPBEAT_ENERGETIC]:
                preset = THEME_PRESETS[theme_name]
                out_path = os.path.join(tmp_dir, f"motif_{theme_name.replace(' ', '_')}.png")
                render_decorative_motif(preset, 1080, 1920, title_text, sub_text, out_path)

                self.assertTrue(os.path.isfile(out_path))
                with Image.open(out_path) as img:
                    self.assertEqual(img.size, (1080, 1920))
                    self.assertEqual(img.mode, "RGBA")
                    # Confirm non-empty drawing (at least some non-zero alpha pixels exist)
                    alpha = np.array(img)[:, :, 3]
                    self.assertGreater(np.count_nonzero(alpha), 500, f"Theme {theme_name} motif is blank")

    def test_render_plan_persistence_vertical_orientation(self):
        """Test build_render_plan records target_resolution and export_orientation."""
        plan = build_render_plan(
            output_file="out.mp4",
            audio_file="audio.mp3",
            video_files=["clip1.mp4"],
            beat_times=[0.0, 1.0],
            segment_durations=[1.0],
            clips=[{"video_file": "clip1.mp4", "start_time": 0.0, "subject_bbox": [0.2, 0.1, 0.6, 0.8]}],
            fps=30.0,
            target_resolution=(1080, 1920),
            export_orientation=ORIENTATION_VERTICAL,
        )
        self.assertEqual(plan["target_resolution"], [1080, 1920])
        self.assertEqual(plan["export_orientation"], ORIENTATION_VERTICAL)
        self.assertEqual(plan["version"], PLAN_VERSION)

    def test_gui_settings_state_includes_export_orientation(self):
        """Test GUI default settings state and keys contain export_orientation."""
        if _default_settings_state is None:
            self.skipTest("Gradio not installed in test environment")
        defaults = _default_settings_state()
        self.assertIn("export_orientation", defaults)
        self.assertEqual(defaults["export_orientation"], ORIENTATION_LANDSCAPE)
        self.assertIn("export_orientation", _SETTINGS_KEYS)
        self.assertIn(ORIENTATION_LANDSCAPE, ORIENTATION_CHOICES)
        self.assertIn(ORIENTATION_VERTICAL, ORIENTATION_CHOICES)


if __name__ == "__main__":
    unittest.main()
