#!/usr/bin/env python3
"""Regression tests for multi-person vertical crop selection."""

import os
import sys
import unittest

import numpy as np

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from subject_detection import nms, select_subject_bbox
from ui_content import (
    VERTICAL_CROP_AUTO_LARGEST,
    VERTICAL_CROP_AUTO_SMALLER,
    VERTICAL_CROP_CENTER,
    VERTICAL_CROP_FOCUS_CHOICES,
)

try:
    from gui import _SETTINGS_KEYS, _default_settings_state
except ImportError:
    _SETTINGS_KEYS = None
    _default_settings_state = None


class TestBabyFocusedCrop(unittest.TestCase):
    def test_nms_collapses_duplicate_anchors_but_keeps_people(self):
        boxes = np.array([
            [0.10, 0.10, 0.50, 0.90],
            [0.11, 0.11, 0.49, 0.89],
            [0.60, 0.35, 0.78, 0.72],
        ])
        scores = np.array([0.90, 0.80, 0.70])
        self.assertEqual(nms(boxes, scores), [0, 2])

    def test_focus_modes_choose_distinct_results(self):
        adult = (0.05, 0.05, 0.65, 0.95)
        baby = (0.53, 0.42, 0.75, 0.78)
        detections = [(0.95, adult), (0.70, baby)]
        self.assertEqual(select_subject_bbox(detections, VERTICAL_CROP_AUTO_SMALLER), baby)
        self.assertEqual(select_subject_bbox(detections, VERTICAL_CROP_AUTO_LARGEST), adult)
        self.assertIsNone(select_subject_bbox(detections, VERTICAL_CROP_CENTER))

    def test_tiny_false_positive_is_not_selected_as_baby(self):
        adult = (0.05, 0.05, 0.65, 0.95)
        noise = (0.49, 0.49, 0.54, 0.54)
        self.assertEqual(
            select_subject_bbox([(0.90, adult), (0.30, noise)], VERTICAL_CROP_AUTO_SMALLER),
            adult,
        )

    def test_gui_setting_defaults_and_persists(self):
        if _default_settings_state is None:
            self.skipTest("Gradio not installed in test environment")
        self.assertEqual(
            _default_settings_state()["vertical_crop_focus"],
            VERTICAL_CROP_AUTO_SMALLER,
        )
        self.assertIn("vertical_crop_focus", _SETTINGS_KEYS)
        self.assertEqual(
            VERTICAL_CROP_FOCUS_CHOICES,
            [VERTICAL_CROP_AUTO_SMALLER, VERTICAL_CROP_AUTO_LARGEST, VERTICAL_CROP_CENTER],
        )


if __name__ == "__main__":
    unittest.main()
