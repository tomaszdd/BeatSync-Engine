#!/usr/bin/env python3
"""Unit tests for the black-frame and motion-blur quality filter."""

import os
import sys
import unittest
import numpy as np

# Add src to sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from subject_detection import (
    DEFAULT_MIN_LUMINANCE,
    DEFAULT_MIN_LAPLACIAN_VAR,
    score_frame_darkness,
    score_frame_blur,
    score_frame_quality,
    is_unusable_quality,
)
from auto_mode.stage6_av_planner import (
    _no_subject_score,
    filter_no_subject_candidates,
)


class TestQualityFilter(unittest.TestCase):
    def test_score_frame_darkness_black_frame(self):
        # Frame with mean luminance ~0.01 (near-pitch black)
        black_frame = np.full((100, 100, 3), 3, dtype=np.uint8)
        metrics = score_frame_darkness([black_frame])
        self.assertLess(metrics["mean_luminance"], DEFAULT_MIN_LUMINANCE)
        self.assertLess(metrics["min_luminance"], DEFAULT_MIN_LUMINANCE)

    def test_score_frame_darkness_normal_frame(self):
        # Frame with normal luminance ~0.40
        normal_frame = np.full((100, 100, 3), 100, dtype=np.uint8)
        metrics = score_frame_darkness([normal_frame])
        self.assertGreater(metrics["mean_luminance"], DEFAULT_MIN_LUMINANCE)
        self.assertGreater(metrics["min_luminance"], DEFAULT_MIN_LUMINANCE)

    def test_score_frame_blur_sharp_vs_blurred(self):
        # Uniform or heavily blurred frame has near-zero Laplacian variance
        blurred_frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        blur_metrics = score_frame_blur([blurred_frame])
        self.assertLess(blur_metrics["min_laplacian"], DEFAULT_MIN_LAPLACIAN_VAR)

        # High-frequency alternating pattern frame has high Laplacian variance
        sharp_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        sharp_frame[::2, ::2] = 255
        sharp_frame[1::2, 1::2] = 255
        sharp_metrics = score_frame_blur([sharp_frame])
        self.assertGreater(sharp_metrics["min_laplacian"], DEFAULT_MIN_LAPLACIAN_VAR)

    def test_is_unusable_quality_darkness(self):
        # Near-total black candidate
        c_dark = {
            "id": "cand_black",
            "brightness": 0.013,
            "min_luminance": 0.005,
            "mean_luminance": 0.012,
            "min_laplacian": 200.0,
            "subject_confidence": 0.0,
        }
        unusable, reason = is_unusable_quality(c_dark)
        self.assertTrue(unusable)
        self.assertEqual(reason, "darkness")

    def test_is_unusable_quality_motion_blur(self):
        # Motion blur smear candidate
        c_blur = {
            "id": "cand_blur",
            "brightness": 0.35,
            "min_luminance": 0.20,
            "mean_luminance": 0.35,
            "min_laplacian": 20.0,  # Below 65.0 threshold
            "mean_laplacian": 54.0,
            "subject_confidence": 0.95,  # Hallucinated or high subject score
        }
        unusable, reason = is_unusable_quality(c_blur)
        self.assertTrue(unusable)
        self.assertEqual(reason, "motion_blur")

    def test_is_unusable_quality_legacy_fallback(self):
        # Candidate from older cache without min_laplacian, but extreme telemetry deviation and jerk
        c_legacy = {
            "id": "cand_legacy_whip",
            "brightness": 0.36,
            "sharpness": 1.0,  # Old averaged metric washed out by second half
            "telemetry_pointed_down": 0.92,
            "telemetry_jerk_score": 0.65,
            "motion": 0.48,
            "subject_confidence": 0.95,
        }
        unusable, reason = is_unusable_quality(c_legacy)
        self.assertTrue(unusable)
        self.assertEqual(reason, "motion_blur")

    def test_is_unusable_quality_valid_fast_pan(self):
        # Fast pan across a real subject (must NOT be excluded)
        c_valid_pan = {
            "id": "cand_pan",
            "brightness": 0.42,
            "min_luminance": 0.35,
            "mean_luminance": 0.42,
            "min_laplacian": 447.0,  # Well above 65.0 threshold
            "mean_laplacian": 555.0,
            "telemetry_pointed_down": 0.15,
            "telemetry_jerk_score": 0.45,
            "motion": 0.35,
            "subject_confidence": 0.85,
        }
        unusable, reason = is_unusable_quality(c_valid_pan)
        self.assertFalse(unusable)
        self.assertIsNone(reason)

    def test_no_subject_score_marks_unusable_as_1(self):
        c_dark = {"brightness": 0.01, "subject_confidence": 0.9}
        # Even with high subject_confidence, darkness causes no_subject_score = 1.0
        self.assertEqual(_no_subject_score(c_dark), 1.0)

        c_blur = {"min_laplacian": 15.0, "subject_confidence": 0.95}
        self.assertEqual(_no_subject_score(c_blur), 1.0)

    def test_filter_no_subject_candidates_excludes_unusable_even_when_slider_off(self):
        c_good = {"id": "good", "brightness": 0.40, "min_laplacian": 300.0, "subject_confidence": 0.8}
        c_dark = {"id": "dark", "brightness": 0.01, "min_laplacian": 10.0, "subject_confidence": 0.0}
        c_blur = {"id": "blur", "brightness": 0.35, "min_laplacian": 25.0, "subject_confidence": 0.9}

        pool = [c_good, c_dark, c_blur]

        # Slider at 0.0 (off) still excludes dark and blurred candidates
        filtered_off = filter_no_subject_candidates(pool, min_subject_confidence=0.0)
        self.assertEqual([c["id"] for c in filtered_off], ["good"])

        # Slider at 0.3 keeps good candidate
        filtered_03 = filter_no_subject_candidates(pool, min_subject_confidence=0.3)
        self.assertEqual([c["id"] for c in filtered_03], ["good"])


if __name__ == "__main__":
    unittest.main()
