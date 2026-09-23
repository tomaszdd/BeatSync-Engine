#!/usr/bin/env python3
"""Unit tests for beat-matched transitions and blur-to-sharp title card."""

import os
import sys
import unittest
import numpy as np

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from auto_mode.stage6_av_planner import (
    compute_beat_transitions,
    compute_clip_handles,
    DEFAULT_TRANSITION_DURATION,
)
from ffmpeg_processing import _build_transition_filtergraph


class TestTransitionsAndTitle(unittest.TestCase):
    def test_compute_beat_transitions_disabled(self):
        durations = [2.0, 3.0, 2.5]
        clips = [{}, {}, {}]
        transitions = compute_beat_transitions(
            planned_clip_sequence=clips,
            segment_durations=durations,
            transitions_enabled=False,
        )
        self.assertEqual(transitions, [None, None])

    def test_compute_beat_transitions_empty_or_single(self):
        self.assertEqual(compute_beat_transitions([], []), [])
        self.assertEqual(compute_beat_transitions([{}], [5.0]), [])

    def test_compute_beat_transitions_percentile_cut_vs_fade(self):
        # 10 boundaries: 9 weak beats (impact=0.2), 1 strong beat (impact=1.0)
        # Strong beat is > 88th percentile -> hard cut (None)
        # Weak beats -> crossfade (DEFAULT_TRANSITION_DURATION)
        durations = [2.0] * 11
        impacts = [0.2] * 9 + [1.0]
        clips = [{}] + [{'impact': imp} for imp in impacts]
        transitions = compute_beat_transitions(
            planned_clip_sequence=clips,
            segment_durations=durations,
            transitions_enabled=True,
        )
        self.assertEqual(len(transitions), 10)
        # First 9 should be crossfades
        for i in range(9):
            self.assertEqual(transitions[i], DEFAULT_TRANSITION_DURATION)
        # 10th (strongest impact) should be hard cut (None)
        self.assertIsNone(transitions[9])

    def test_compute_beat_transitions_duration_clamping(self):
        # If adjacent clips are very short (e.g. 0.5s), max transition is 0.45 * 0.5 = 0.225s
        durations = [0.5, 0.5]
        clips = [{}, {'impact': 0.1}]
        transitions = compute_beat_transitions(
            planned_clip_sequence=clips,
            segment_durations=durations,
            transitions_enabled=True,
        )
        self.assertEqual(len(transitions), 1)
        self.assertAlmostEqual(transitions[0], 0.225, places=3)

    def test_compute_clip_handles(self):
        durations = [2.0, 3.0, 4.0]
        # Transition 0: 0.35s fade; Transition 1: None (hard cut)
        transitions = [0.35, None]
        in_handles, out_handles = compute_clip_handles(durations, transitions)

        # Clip 0: first clip -> in_handle=0.0, out_handle = 0.35 / 2 = 0.175
        self.assertEqual(in_handles[0], 0.0)
        self.assertAlmostEqual(out_handles[0], 0.175)

        # Clip 1: in_handle = 0.175, out_handle = 0.0 (hard cut to clip 2)
        self.assertAlmostEqual(in_handles[1], 0.175)
        self.assertEqual(out_handles[1], 0.0)

        # Clip 2: last clip -> in_handle = 0.0, out_handle = 0.0
        self.assertEqual(in_handles[2], 0.0)
        self.assertEqual(out_handles[2], 0.0)

    def test_filtergraph_all_hard_cuts(self):
        video_files = ["clip0.mp4", "clip1.mp4", "clip2.mp4"]
        transitions = [None, None]
        durations = [2.0, 3.0, 2.5]
        input_args, filter_str = _build_transition_filtergraph(video_files, transitions, durations)
        # Should contain concat of 3 blocks with no xfade
        self.assertNotIn("xfade", filter_str)
        self.assertIn("concat=n=3:v=1:a=0", filter_str)

    def test_filtergraph_all_crossfades(self):
        video_files = ["clip0.mp4", "clip1.mp4", "clip2.mp4"]
        transitions = [0.35, 0.35]
        durations = [2.0, 3.0, 2.5]
        input_args, filter_str = _build_transition_filtergraph(video_files, transitions, durations)
        # Should be a single block containing 2 xfades
        self.assertIn("xfade=transition=fade", filter_str)
        # First xfade offset: 2.0 - 0.35/2 = 1.825
        self.assertIn("offset=1.825", filter_str)
        # Second xfade offset: (2.0 + 3.0) - 0.35/2 = 4.825
        self.assertIn("offset=4.825", filter_str)
        self.assertIn("[outv]", filter_str)

    def test_filtergraph_mixed_transitions(self):
        # Clip 0 (2.0s) -> fade (0.35s) -> Clip 1 (3.0s) -> cut (None) -> Clip 2 (2.0s)
        # Block 0: clips [0, 1] with 1 xfade. Duration: 2.0 + 3.0 = 5.0s
        # Block 1: clip [2] plain. Duration: 2.0s
        # Total: concat of 2 blocks = 7.0s
        video_files = ["clip0.mp4", "clip1.mp4", "clip2.mp4"]
        transitions = [0.35, None]
        durations = [2.0, 3.0, 2.0]
        input_args, filter_str = _build_transition_filtergraph(video_files, transitions, durations)
        self.assertIn("xfade=transition=fade", filter_str)
        self.assertIn("concat=n=2:v=1:a=0", filter_str)


if __name__ == "__main__":
    unittest.main()
