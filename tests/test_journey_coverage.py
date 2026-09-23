import os
import sys
import unittest

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from auto_mode.stage6_av_planner import (
    _merge_contiguous_candidates,
    _select_non_overlapping_start,
    _journey_chapter_counts,
    _build_journey_sequence,
    _source_usable_seconds,
)


class TestJourneyCoverage(unittest.TestCase):
    def test_merge_contiguous_candidates_overlapping(self):
        """Overlapping chunks from the same continuous recording should be merged."""
        cands = [
            {
                "id": "c0",
                "video_file": "vid.mp4",
                "video_duration": 7.39,
                "start": 0.0,
                "end": 5.2,
                "editorial_score": 0.4,
            },
            {
                "id": "c1",
                "video_file": "vid.mp4",
                "video_duration": 7.39,
                "start": 3.7,
                "end": 7.39,
                "editorial_score": 0.8,
            },
        ]
        merged = _merge_contiguous_candidates(cands)
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["start"], 0.0)
        self.assertAlmostEqual(merged[0]["end"], 7.39)
        self.assertAlmostEqual(merged[0]["editorial_score"], 0.8)

    def test_merge_contiguous_candidates_disjoint(self):
        """Chunks separated by a gap (e.g. quality-filtered scene cut) must not be merged."""
        cands = [
            {
                "id": "c0",
                "video_file": "vid.mp4",
                "video_duration": 20.0,
                "start": 0.0,
                "end": 5.0,
            },
            {
                "id": "c1",
                "video_file": "vid.mp4",
                "video_duration": 20.0,
                "start": 10.0,
                "end": 15.0,
            },
        ]
        merged = _merge_contiguous_candidates(cands)
        self.assertEqual(len(merged), 2)
        self.assertAlmostEqual(merged[0]["end"], 5.0)
        self.assertAlmostEqual(merged[1]["start"], 10.0)

    def test_select_non_overlapping_start_epsilon_tolerance(self):
        """Floating point precision must not reject a cut that fits allowed bounds within epsilon."""
        cand = {
            "video_file": "vid.mp4",
            "video_duration": 7.390717,
            "start": 0.0,
            "end": 7.390717,
        }
        profile = {"duration": 3.53, "target": "flow"}
        # Edge buffer 2.0s: allowed_lo = 2.0, allowed_hi = 2.0
        start = _select_non_overlapping_start(cand, profile, {}, edge_buffer_seconds=2.0)
        self.assertIsNotNone(start)
        self.assertAlmostEqual(start, 2.0, places=2)

    def test_select_non_overlapping_start_end_rounding(self):
        """Candidate end rounded in cache to 3 decimal places should snap to video_duration."""
        cand = {
            "video_file": "short.mp4",
            "video_duration": 4.2042,
            "start": 0.0,
            "end": 4.204,  # Truncated in JSON
        }
        profile = {"duration": 3.60, "target": "flow"}
        start = _select_non_overlapping_start(cand, profile, {}, edge_buffer_seconds=2.0)
        self.assertIsNotNone(start)
        self.assertAlmostEqual(start, 0.6042, places=3)

    def test_journey_chapter_counts_guaranteed_floor_and_surplus(self):
        """Every eligible footage source gets 1 base clip; surplus goes to larger sources."""
        chapters = [
            {"kind": "footage", "src": "short1.mp4"},
            {"kind": "footage", "src": "short2.mp4"},
            {"kind": "footage", "src": "long1.mp4"},
            {"kind": "footage", "src": "long2.mp4"},
        ]
        # Short sources have 0 surplus footage; long sources have surplus footage
        budget = {
            "short1.mp4": 0.0,
            "short2.mp4": 0.0,
            "long1.mp4": 20.0,
            "long2.mp4": 40.0,
        }
        n = 10
        counts = _journey_chapter_counts(chapters, n, budget)
        self.assertEqual(sum(counts), 10)
        # short sources get guaranteed 1 clip each
        self.assertEqual(counts[0], 1)
        self.assertEqual(counts[1], 1)
        # long sources split the remaining 6 surplus segments
        self.assertGreater(counts[2], 1)
        self.assertGreater(counts[3], counts[2])
        self.assertEqual(counts[0] + counts[1] + counts[2] + counts[3], 10)

    def test_journey_chapter_counts_fewer_segments_than_sources(self):
        """When total output segments < number of sources, total segment count is strictly n."""
        chapters = [
            {"kind": "footage", "src": f"src_{i}.mp4"}
            for i in range(10)
        ]
        budget = {f"src_{i}.mp4": float(i + 1) for i in range(10)}
        n = 5
        counts = _journey_chapter_counts(chapters, n, budget)
        self.assertEqual(sum(counts), 5)
        # Top 5 longest sources get 1 clip, others 0
        for i in range(5):
            self.assertEqual(counts[9 - i], 1)
        for i in range(5):
            self.assertEqual(counts[i], 0)

    def test_journey_source_coverage_real_short_sources(self):
        """Verify that short sources with usable >= 0.2 each appear at least once in full sequence."""
        # 4 short sources and 1 long source
        candidates = [
            {"id": "c1", "video_file": "GX013843.MP4", "video_duration": 4.5, "start": 0.0, "end": 4.5},
            {"id": "c2", "video_file": "GX013844.MP4", "video_duration": 4.2042, "start": 0.0, "end": 4.204},
            # GX013845 split into two 5.2s candidate chunks
            {"id": "c3_a", "video_file": "GX013845.MP4", "video_duration": 7.39, "start": 0.0, "end": 5.2},
            {"id": "c3_b", "video_file": "GX013845.MP4", "video_duration": 7.39, "start": 3.7, "end": 7.39},
            # GX013846 split into two chunks
            {"id": "c4_a", "video_file": "GX013846.MP4", "video_duration": 7.59, "start": 0.0, "end": 5.2},
            {"id": "c4_b", "video_file": "GX013846.MP4", "video_duration": 7.59, "start": 3.8, "end": 7.59},
            # Long source
            {"id": "c5_a", "video_file": "GX013848.MP4", "video_duration": 30.0, "start": 0.0, "end": 5.2},
            {"id": "c5_b", "video_file": "GX013848.MP4", "video_duration": 30.0, "start": 4.0, "end": 15.0},
            {"id": "c5_c", "video_file": "GX013848.MP4", "video_duration": 30.0, "start": 14.0, "end": 30.0},
        ]
        # Timestamps order: GX013843, GX013844, GX013845, GX013846, GX013848
        # Profiles starting with long durations that previously choked short sources
        profiles = [
            {"duration": 0.93, "target": "flow", "start": 0.0, "end": 0.93},
            {"duration": 3.60, "target": "flow", "start": 0.93, "end": 4.53},
            {"duration": 3.53, "target": "flow", "start": 4.53, "end": 8.06},
            {"duration": 1.83, "target": "flow", "start": 8.06, "end": 9.89},
            {"duration": 2.00, "target": "flow", "start": 9.89, "end": 11.89},
            {"duration": 2.00, "target": "flow", "start": 11.89, "end": 13.89},
            {"duration": 2.00, "target": "flow", "start": 13.89, "end": 15.89},
        ]
        plan = _build_journey_sequence(
            profiles=profiles,
            candidates=candidates,
            edge_buffer_seconds=2.0,
            first_video=None,
            last_video=None,
        )
        self.assertEqual(len(plan), len(profiles))
        sources_used = {c["video_file"] for c in plan}
        self.assertIn("GX013843.MP4", sources_used)
        self.assertIn("GX013844.MP4", sources_used)
        self.assertIn("GX013845.MP4", sources_used)
        self.assertIn("GX013846.MP4", sources_used)
        self.assertIn("GX013848.MP4", sources_used)

    def test_unusable_source_not_forced(self):
        """Sources with usable < 0.2 (like fully black footage) must still receive 0 clips."""
        candidates = [
            # Usable source
            {"id": "c1", "video_file": "good.mp4", "video_duration": 10.0, "start": 0.0, "end": 10.0},
            # Edge buffer 2.0 means bounds [2.0, 0.1] -> usable < 0.2
            {"id": "c2", "video_file": "dead.mp4", "video_duration": 2.1, "start": 2.0, "end": 2.05},
        ]
        profiles = [
            {"duration": 2.0, "target": "flow", "start": 0.0, "end": 2.0},
            {"duration": 2.0, "target": "flow", "start": 2.0, "end": 4.0},
        ]
        plan = _build_journey_sequence(
            profiles=profiles,
            candidates=candidates,
            edge_buffer_seconds=2.0,
            first_video=None,
            last_video=None,
        )
        self.assertEqual(len(plan), 2)
        sources_used = [c["video_file"] for c in plan]
        self.assertNotIn("dead.mp4", sources_used)
        self.assertEqual(sources_used, ["good.mp4", "good.mp4"])


if __name__ == "__main__":
    unittest.main()
