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

from ffmpeg_processing import (
    _title_font_size,
    approximate_head_region,
    build_crop_to_fill_filter,
    build_fit_scale_filter,
    calculate_settled_crop_x,
    _ULTRA_SHORT_CLIP_FLOOR,
)
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


def _split_unescaped(text: str, sep: str) -> list:
    """Split on `sep`, treating a backslash-escaped `\\sep` as a literal (not a split
    point) per ffmpeg filtergraph escaping -- and unescape it back to a plain `sep` in
    the result, since callers want the value ffmpeg itself would see."""
    placeholder = "\x00"
    protected = text.replace("\\" + sep, placeholder)
    return [p.replace(placeholder, sep) for p in protected.split(sep)]


def _extract_crop_x_field(filter_str: str) -> str:
    """Pull the raw crop_x field out of a 'crop=w:h:x:y' filter, honoring the
    backslash-escaped comma an eased expression's min(1\\,t/E) may contain."""
    crop_args = _split_unescaped(filter_str.split("crop=")[1], ",")[0]
    return crop_args.split(":")[2]


def _resolve_crop_x(raw: str, t: float) -> float:
    """Resolve a crop_x field that may be a plain int or an eased ffmpeg expr.

    Eased expressions use 't' (seconds) and '^' (power); evaluate them the same
    way ffmpeg would at a given t so tests can assert on start/mid/settled values.
    """
    try:
        return float(int(raw))
    except ValueError:
        return eval(raw.replace('^', '**'), {"min": min, "t": t})  # noqa: S307


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
        """A subject wider than the fill window gets the protected fit fallback."""
        bbox = (0.20, 0.1, 0.526, 0.9)
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        self.assertIn("pad=1080:1920:0:(oh-ih)/2:color=black", filter_str)

    def test_build_crop_to_fill_filter_clamping_left_edge(self):
        """Test subject on far left of 4K frame clamps crop window to 0 (once settled)."""
        bbox = (0.01, 0.1, 0.09, 0.9)  # cx = 0.05
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        crop_x = _resolve_crop_x(_extract_crop_x_field(filter_str), t=10.0)
        self.assertEqual(crop_x, 0, "Far-left subject must clamp crop_x to 0")

    def test_build_crop_to_fill_filter_clamping_right_edge(self):
        """Test subject on far right of 4K frame clamps crop window to max_x (once settled)."""
        bbox = (0.91, 0.1, 0.99, 0.9)  # cx = 0.95
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        crop_x = _resolve_crop_x(_extract_crop_x_field(filter_str), t=10.0)
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

    def test_wide_subject_uses_zoom_out_letterbox_fallback(self):
        """A protected subject wider than the fill window must not be side-clipped."""
        bbox = (0.73, 0.00, 1.00, 0.98)
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox)
        self.assertIn("pad=1080:1920:0:(oh-ih)/2:color=black", filter_str)
        self.assertIn("crop=1080:", filter_str)

    def test_head_proxy_is_top_slice_with_full_horizontal_extent(self):
        bbox = (0.73, 0.10, 1.00, 0.90)
        self.assertEqual(approximate_head_region(bbox), (0.73, 0.10, 1.00, 0.26))

    def test_edge_head_guard_zooms_out_instead_of_slicing_face(self):
        bbox = (0.73, 0.00, 1.00, 0.98)
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, bbox)
        scale_part = filter_str.split("scale=")[1].split(",")[0].split(":")
        scaled_width = int(scale_part[0])
        crop_x = _resolve_crop_x(_extract_crop_x_field(filter_str), t=10.0)
        visible_x0 = crop_x / scaled_width
        visible_x1 = (crop_x + 1080) / scaled_width
        self.assertLessEqual(visible_x0, bbox[0])
        self.assertGreaterEqual(visible_x1, bbox[2])

    def test_crop_ease_starts_centered_and_settles_at_final_offset(self):
        """Off-center subject: x should start at frame center and ease to the final offset."""
        bbox = (0.91, 0.1, 0.99, 0.9)  # far right, cx = 0.95
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=2.0)
        crop_x_raw = _extract_crop_x_field(filter_str)
        self.assertIn("t/", crop_x_raw, "Off-center offset should produce a time-varying expression")
        start_x = _resolve_crop_x(crop_x_raw, t=0.0)
        mid_x = _resolve_crop_x(crop_x_raw, t=0.2)
        end_x = _resolve_crop_x(crop_x_raw, t=10.0)
        max_x = 3414 - 1080
        self.assertAlmostEqual(start_x, (3414 - 1080) / 2.0, delta=2, msg="Ease must start near geometric center")
        self.assertEqual(end_x, max_x)
        self.assertTrue(start_x < mid_x < end_x, "Mid-ease value must lie strictly between start and end")

    def test_crop_ease_clamps_for_short_clips(self):
        """A clip much shorter than the nominal ease window must fully settle well before it ends."""
        bbox = (0.91, 0.1, 0.99, 0.9)
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=0.5)
        crop_x_raw = _extract_crop_x_field(filter_str)
        # min(0.4, 0.5*0.4) = 0.2s ease window -- must be fully settled by 0.3s into a 0.5s clip.
        settled_early = _resolve_crop_x(crop_x_raw, t=0.3)
        settled_late = _resolve_crop_x(crop_x_raw, t=10.0)
        self.assertEqual(settled_early, settled_late, "Short clip must settle well before its own end")

    def test_crop_ease_skipped_when_final_offset_is_already_center(self):
        """No bbox (or an effectively-centered one) must render a static crop_x, not an expression."""
        filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=None, clip_duration=2.0)
        crop_x_raw = _extract_crop_x_field(filter_str)
        int(crop_x_raw)  # must parse as a plain integer -- no ease expression at all

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

    def test_crop_ease_crossfade_starts_from_previous_settled_crop_x(self):
        """Crossfade boundary: incoming clip starts at outgoing clip's settled crop_x."""
        bbox = (0.91, 0.1, 0.99, 0.9)  # settled crop_x = 2334
        initial_crop_x = 200
        transition_duration = 0.35
        filter_str = build_crop_to_fill_filter(
            3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=2.0,
            initial_crop_x=initial_crop_x, transition_duration=transition_duration,
        )
        crop_x_raw = _extract_crop_x_field(filter_str)
        self.assertIn("t/", crop_x_raw, "Crossfade ease should produce an expression")
        start_x = _resolve_crop_x(crop_x_raw, t=0.0)
        end_x = _resolve_crop_x(crop_x_raw, t=10.0)
        self.assertEqual(start_x, initial_crop_x, "Must start at previous clip's settled crop_x")
        self.assertEqual(end_x, 2334, "Must settle at current clip's final crop_x")
        # At end of crossfade window (t=0.35), should be partway through smooth ease
        mid_x = _resolve_crop_x(crop_x_raw, t=0.35)
        self.assertTrue(start_x < mid_x < end_x, "Must continue easing smoothly past crossfade")

    def test_crop_ease_hard_cut_starts_from_frame_center(self):
        """Hard cut boundary: incoming clip starts at frame center (neutral_x)."""
        bbox = (0.91, 0.1, 0.99, 0.9)  # settled crop_x = 2334
        filter_str = build_crop_to_fill_filter(
            3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=2.0,
            initial_crop_x=None, transition_duration=None,
        )
        crop_x_raw = _extract_crop_x_field(filter_str)
        start_x = _resolve_crop_x(crop_x_raw, t=0.0)
        end_x = _resolve_crop_x(crop_x_raw, t=10.0)
        neutral_x = (3414 - 1080) // 2
        self.assertAlmostEqual(start_x, neutral_x, delta=2, msg="Hard cut must start at center")
        self.assertEqual(end_x, 2334)

    def test_crop_ease_skipped_for_ultra_short_clip(self):
        """Clips below the ultra-short floor must render a plain static crop_x integer."""
        bbox = (0.91, 0.1, 0.99, 0.9)
        # clip duration 0.20s is well below 0.40s floor
        filter_str = build_crop_to_fill_filter(
            3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=0.20,
        )
        crop_x_raw = _extract_crop_x_field(filter_str)
        int(crop_x_raw)  # must parse as plain integer with no expression
        self.assertNotIn("t/", crop_x_raw)

    def test_calculate_settled_crop_x_matches_filter_output(self):
        """calculate_settled_crop_x must exactly match the settled crop_x from build_crop_to_fill_filter."""
        test_bboxes = [
            None,
            (0.01, 0.1, 0.1, 0.9),  # left edge -> crop_x 0
            (0.45, 0.1, 0.55, 0.9),  # near center -> neutral_x 1168
            (0.91, 0.1, 0.99, 0.9),  # right edge -> max_x 2334
        ]
        for bbox in test_bboxes:
            expected = calculate_settled_crop_x(3840, 2160, 1080, 1920, bbox)
            filter_str = build_crop_to_fill_filter(3840, 2160, 1080, 1920, subject_bbox=bbox, clip_duration=2.0)
            crop_x_raw = _extract_crop_x_field(filter_str)
            settled = int(_resolve_crop_x(crop_x_raw, t=10.0))
            self.assertEqual(expected, settled)

    def test_prepare_vertical_crop_continuity_wires_crossfades_and_ultra_short(self):
        """Test prepare_vertical_crop_continuity properly wires crossfades, hard cuts, and ultra-short clips."""
        from video_processor import prepare_vertical_crop_continuity
        planned_clips = [
            {"video_file": "clip0.mp4", "start_time": 0.0, "source_duration": 0.067},  # ultra-short (0.067s)
            {"video_file": "clip1.mp4", "start_time": 0.0, "source_duration": 3.9},   # normal, subject right
            {"video_file": "clip2.mp4", "start_time": 0.0, "source_duration": 2.0},   # normal, subject left
        ]
        durations = [0.067, 3.9, 2.0]
        transitions = [None, 0.35]  # boundary 0->1: hard cut; boundary 1->2: crossfade
        in_handles = [0.0, 0.0, 0.175]
        out_handles = [0.0, 0.175, 0.0]

        # Give clip 1 and clip 2 distinct bboxes
        planned_clips[1]["subject_bbox"] = (0.91, 0.1, 0.99, 0.9)  # right edge
        planned_clips[2]["subject_bbox"] = (0.01, 0.1, 0.10, 0.9)  # left edge

        # Mock resolution retrieval to return 3840x2160 for all
        import video_processor
        orig_get_res = video_processor.get_video_resolution
        video_processor.get_video_resolution = lambda vf: (3840, 2160)
        try:
            prepare_vertical_crop_continuity(
                planned_clips, durations, transitions, in_handles, out_handles,
                target_size=(1080, 1920), vertical_crop_focus="Auto",
            )
            # Clip 0: ultra-short, inherited Clip 1 bbox, skip_ease=True, ultra_short_skip=True
            self.assertTrue(planned_clips[0]["ultra_short_skip"])
            self.assertTrue(planned_clips[0]["skip_ease"])
            self.assertFalse(planned_clips[0]["crop_ease"])
            self.assertEqual(planned_clips[0]["subject_bbox"], planned_clips[1]["subject_bbox"])

            # Clip 1: hard cut -> crop_initial_x="center", crop_ease=True
            self.assertEqual(planned_clips[1]["crop_initial_x"], "center")
            self.assertIsNone(planned_clips[1]["initial_crop_x"])
            self.assertTrue(planned_clips[1]["crop_ease"])

            # Clip 2: crossfade -> initial_crop_x = Clip 1's settled crop_x (2334), transition_duration=0.35
            self.assertEqual(planned_clips[2]["initial_crop_x"], planned_clips[1]["crop_settled_x"])
            self.assertEqual(planned_clips[2]["transition_duration"], 0.35)
            self.assertTrue(planned_clips[2]["crop_ease"])
        finally:
            video_processor.get_video_resolution = orig_get_res


if __name__ == "__main__":
    unittest.main()

