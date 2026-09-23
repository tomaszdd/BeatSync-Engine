# Journey Mode Source Coverage Guarantee — Implementation Report

## Summary

In Auto Mode's forward-chronological `journey` mode, footage and still-image loops are arranged in capture-time order to preserve the emotional progression of an event. In previous renders (e.g. `music_video_v4_journey_20260923_132414.mp4` on `um890`), shorter source recordings were completely missing from the final cut:
- **`GX013844.MP4`** (4.2s), **`GX013845.MP4`** (7.4s), **`GX013846.MP4`** (7.6s), and **`GX013847.MP4`** (7.0s) were each budgeted `x2` chapters in the planner debug log, but received **zero actual clips** in the final render plan.
- Their combined shortfall (8 segments) rolled forward into subsequent chapters, landing disproportionately on **`GX013848.MP4`** (6 clips) and **`GX013849.MP4`** (10 clips).
- Distinct real-life recorded moments from a family birth were completely omitted, while a single longer recording dominated almost a third of the final 33-clip timeline.

This implementation resolves this issue at its root causes:
1. **Guaranteed 1-clip floor per eligible source (`usable >= 0.2s`)**: Every footage chapter with usable footage gets first claim to at least 1 delivered segment before any surplus segments are distributed.
2. **Surplus quota distribution**: Surplus segments beyond the floor are distributed proportionally to each source's *surplus* usable duration beyond the floor requirement (~3.0s cut/buffer), preventing short clips from receiving quota they cannot physically deliver.
3. **Continuous candidate chunk merging**: Overlapping candidate chunks from the same continuous recording (previously split into 5.2s chunks by `video_analysis.py`) are unified into continuous usable windows in journey mode, allowing longer beat cuts (e.g. 3.5s - 3.6s) to be fulfilled cleanly without crossing artificial chunk boundaries.
4. **Floating-point epsilon tolerance in gap picking**: Corrected sub-millisecond precision rejections in `_select_non_overlapping_start()` and `_pick_start_from_available_gaps()`.

Verified end-to-end on real hardware (`um890`) against real GoPro HERO10 footage:
- All four previously omitted sources (`GX013844`, `GX013845`, `GX013846`, `GX013847`) now each appear in the final cut.
- Total clip count matches exactly 33 clips (zero off-by-one regressions).
- Defective footage (`GX013854`, pitch black in bag) correctly receives 0 clips.
- Chronological forward-only playback ordering is 100% preserved.
- All 17 unit tests pass.

---

## Root Cause Analysis

Tracing the exact planning execution of `music_video_v4_journey_20260923_132414.plan.json` on `um890` revealed why the four sources were skipped:

### 1. Artificial 5.2s Candidate Chunk Boundaries Colliding with Edge Buffers

In `video_analysis.py` (`_make_candidate_windows()`), any detected scene longer than `max_window = 5.2s` is split into overlapping chunks of at most 5.2 seconds (e.g. `[0.0, 5.2]` and `[3.7, 7.39]` for `GX013845.MP4`).

In `stage6_av_planner.py`, `_journey_forward_start()` iterated through individual candidates and passed each isolated chunk to `_select_non_overlapping_start()`.
With `edge_buffer_seconds = 2.0`:
- For a beat cut of duration `3.60s` or `3.53s` (which occurred at Segments 1 and 2 of the 60s audio), `_buffered_start_bounds` set `allowed_lo = 2.0s`.
- For candidate chunk 0 (`end = 5.2s`), the usable window end was clamped to `5.2s`.
- The maximum allowed start time became `window_end - source_duration = 5.2 - 3.53 = 1.67s`.
- Because `max_start (1.67s) < window_start (2.00s)`, chunk 0 was rejected.
- Chunk 1 started at `3.70s`, so its window start was `max(2.0, 3.70) = 3.70s`, while its maximum start was `(2.0 + 3.53) - 3.53 = 2.00s`. Because `2.00s < 3.70s`, chunk 1 was also rejected.

Even though `GX013845.MP4` is a continuous 7.39-second recording with ample room for a 3.53s cut at offset 2.0s (running from 2.00s to 5.53s, leaving 1.86s of buffer at the end), neither isolated 5.2s chunk could accommodate it independently.

### 2. Floating-Point Precision Rejections in `_select_non_overlapping_start()` and `_pick_start_from_available_gaps()`

For single-chunk sources like `GX013844.MP4` (video duration 4.2042s, JSON candidate `end` rounded to 4.204s) and for `GX013845.MP4` with duration 3.53s:
- In `_select_non_overlapping_start()`:
  `window_end = allowed_hi + source_duration = 2.0 + 3.53 = 5.529999999999999`
  `max_start = window_end - source_duration = 1.9999999999999996`
  `window_start = 2.0`
  The strict check `if max_start < window_start:` evaluated to `True` due to a $4 \times 10^{-16}$ IEEE 754 precision artifact, returning `None`.
- In `_pick_start_from_available_gaps()`:
  `window_end - window_start = 5.529999999999999 - 2.0 = 3.5299999999999993`
  The strict check `if window_end - window_start < source_duration:` (`3.5299999999999993 < 3.53`) rejected the entire search window before evaluating any gaps.

### 3. Compounding Deficit Rollover and Linear Pointer Freezing

Because Segment 1 required a long cut (3.60s), `GX013844` failed on Segment 1. Its `got` count was 0, so its full quota (2) became `deficit = 2`.
Crucially, **the timeline segment pointer `seg` did not advance**; it remained at Segment 1.
When the loop advanced to Chapter 2 (`GX013845`), `GX013845` was also tested against Segment 1 (3.60s) with an increased quota of 4. It also failed, leaving `seg = 1` and increasing deficit to 4.
Chapters 3 (`GX013846`) and 4 (`GX013847`) suffered the identical fate.
Finally, Chapter 5 (`GX013848`, 32.5s) was reached. Being 32 seconds long, it satisfied Segment 1 and consumed 6 clips to absorb the massive accumulated deficit. Chapters 1–4 were never reconsidered for shorter subsequent segments (such as Segment 3 at 1.83s or Segment 6 at 1.40s) because chapters were iterated sequentially in a single pass.

---

## Architectural Decisions & Tradeoffs

### 1. The Guaranteed Floor Tradeoff
In `_journey_chapter_counts()`:
- When available output segments `remaining >= len(foot_idx)`, every footage source with `usable >= 0.2` is granted a **guaranteed base allocation of 1 delivered clip**.
- If total output segments are fewer than the number of sources (`remaining < len(foot_idx)`), `_largest_remainder` allocates 1 clip to the highest-budget sources so total output segments strictly equal `n`.

**Tradeoff**: Guaranteeing a floor of 1 clip per eligible source slightly reduces the total number of clips available to long "anchor" recordings (e.g. `GX013849` received 7 clips instead of 10). However, in journey mode, chronological diversity is the primary editorial objective: capturing every real recorded moment once is fundamentally superior to letting one long recording dominate the entire runtime while short moments are completely lost.

### 2. Surplus Weighting Math (Avoiding Overshoot/Undershoot)
Previously, `budget` gave relative weights using square-root scaling `(usable / mean) ** 0.5` with a floor of `0.4`. Because of this 0.4 floor, short sources (even with only 0.2s of usable footage) received ~20% of the weight of a 120s source, causing `_largest_remainder` to budget them 2 clips. Since a 4.2s clip cannot physically deliver 2 non-overlapping clips under edge buffering, it was guaranteed to shortfall and generate deficit.

The surplus formula now explicitly subtracts the floor footage:
$$\text{surplus}[v] = \max(0.0, \text{usable}[v] - \text{floor\_sec})$$
where $\text{floor\_sec} = 3.0\text{s}$ (the footage consumed by the guaranteed 1st clip plus edge buffer).
- Sources with $\le 3.0\text{s}$ usable footage have `surplus = 0.0`, so they receive `1 + 0 = 1` clip.
- Sources with $> 3.0\text{s}$ usable footage split the remaining `remaining - len(foot_idx)` surplus segments proportionally to their surplus.
- Because $\sum \text{alloc} = \text{len(foot\_idx)} + (\text{remaining} - \text{len(foot\_idx)}) = \text{remaining}$, the segment sum **strictly equals $n$** with zero overshoot, zero undershoot, and zero artificial deficit.

### 3. Continuous Candidate Merging
In `_merge_contiguous_candidates()`, adjacent or overlapping candidate chunks within the same continuous recording (`next_start <= curr_end + 0.1`) are merged into a single contiguous window.
- Candidate tags and the highest editorial scores are preserved.
- Genuinely disconnected scenes or footage with quality-filtered gaps (e.g. black-frame exclusions) are preserved as separate disjoint candidates.

---

## What Changed

| File | Change |
|---|---|
| `src/auto_mode/stage6_av_planner.py` | Added `_merge_contiguous_candidates()` to unify artificial 5.2s candidate chunks within continuous footage in journey mode. |
| `src/auto_mode/stage6_av_planner.py` | Updated `_select_non_overlapping_start()` to handle candidate `end` rounding near `video_duration` (within 0.05s) and added `1e-4` epsilon tolerance to `max_start < window_start`. |
| `src/auto_mode/stage6_av_planner.py` | Updated `_pick_start_from_available_gaps()` to use `1e-4` epsilon tolerance on window and gap duration comparisons. |
| `src/auto_mode/stage6_av_planner.py` | Updated `_build_journey_sequence()` to merge continuous footage chunks, calculate surplus weights beyond the 3.0s floor, and ensure 1 clip per eligible source. |
| `src/auto_mode/stage6_av_planner.py` | Updated `_journey_chapter_counts()` documentation and surplus allocation. |
| `tests/test_journey_coverage.py` | **New.** 8 comprehensive unit tests covering candidate chunk merging, epsilon tolerance in start bounds, end-rounding guards, guaranteed floor quota math, constrained segment totals, and end-to-end multi-chapter coverage. |

---

## Real-Hardware Verification (`um890`)

### Verification Setup
- **Host**: Minisforum UM890 Pro (`um890`), AMD Ryzen 9 8945HS with Radeon 780M iGPU.
- **Python**: `C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe` (Python 3.12.10).
- **Test Footage**: `D:\Photos\GoPro\2025-10-01 Tereska Birth\` (15 GoPro HERO10 Black MP4 files, 19.4 minutes total).
- **Audio**: `C:\BeatSyncTest\audio_60s.mp3` (60.03s duration).
- **Settings**: `clip_order_mode='journey'`, `min_subject_confidence=0.3`.
- **Cache**: Warm analysis cache in `input/video_analysis_cache/`.

### 1. Unit Tests
Executed directly on `um890`:
```
C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe -m unittest discover tests
Ran 17 tests in 0.228s
OK
```
All 9 quality filter tests and all 8 journey source coverage tests passed.

### 2. End-to-End Render Execution
Re-ran `run_v4_journey.py` on `um890`:
- **Stage 5 (Visual Analysis)**: 0.0s (15/15 cache hits).
- **Stage 6 (AV Planner)**: Planned all 33 clips in forward-chronological order across 13 sources. 0 held beats, 0 still fallbacks.
- **Stage 7 (Video Assembly)**: Rendered output `music_video_v4_journey_20260923_134417.mp4` via AMD AMF (`h264_amf`) in 39 seconds total.
- **Output Video**: 3840x2160 (4K UHD) @ 30.00 FPS, 1800 frames, 60.00s, 177.8 MB.

### 3. Before vs After Per-Source Clip Distribution

Evaluated via `Counter(c['source_name'] for c in clips)` from the plan JSON files:

| Source File | Usable Duration | Old Plan (`132414`) | New Plan (`134417`) | Outcome |
|---|---|---|---|---|
| **`GX013843.MP4`** | 4.07s | 1 | 1 | Preserved |
| **`GX013844.MP4`** | 0.20s | **0** | **1** | **Fixed** (Clip 1, t=0.60s - 4.20s) |
| **`GX013845.MP4`** | 3.39s | **0** | **1** | **Fixed** (Clip 2, t=2.00s - 5.53s) |
| **`GX013846.MP4`** | 3.59s | **0** | **1** | **Fixed** (Clip 3, t=2.00s - 3.83s) |
| **`GX013847.MP4`** | 2.96s | **0** | **1** | **Fixed** (Clip 4, t=2.00s - 3.97s) |
| **`GX013848.MP4`** | 28.48s | 6 | 3 | Balanced surplus |
| **`GX013849.MP4`** | 107.03s | 10 | 7 | Balanced surplus |
| **`GX013850.MP4`** | 40.31s | 3 | 3 | Preserved |
| **`GX013851.MP4`** | 3.39s | 1 | 1 | Preserved |
| **`GX013852.MP4`** | 3.74s | 1 | 1 | Preserved |
| **`GX013853.MP4`** | 34.39s | 4 | 3 | Balanced surplus |
| **`GX013854.MP4`** | 0.00s | 0 | 0 | **Correctly 0** (unusable black footage excluded) |
| **`GX013855.MP4`** | 120.36s | 4 | 7 | Proportional surplus |
| **`GX013856.MP4`** | 70.69s | 3 | 3 | Preserved |
| **`GX023854.MP4`** | 0.00s | 0 | 0 | **Correctly 0** (unusable footage excluded) |
| **Total Clips** | | **33** | **33** | **Exact match to audio beats** |

### 4. Verification of Specific Requirements
1. **At Least One Clip Per Usable Source**: `GX013844`, `GX013845`, `GX013846`, and `GX013847` each appear exactly once in their proper chronological positions (Clips 1, 2, 3, and 4).
2. **Total Clip Count**: Total clip count is exactly 33 clips, matching the 33 segment profiles (zero off-by-one errors).
3. **Unusable Footage Protection**: `GX013854` (black screen in pocket) and `GX023854` have `usable < 0.2s` and receive 0 clips.
4. **Monotonic Forward Chronological Order**: The clips progress strictly forward by recording timestamp:
   `GX013843` $\rightarrow$ `GX013844` $\rightarrow$ `GX013845` $\rightarrow$ `GX013846` $\rightarrow$ `GX013847` $\rightarrow$ `GX013848` $\rightarrow$ `GX013849` $\rightarrow$ `GX013850` $\rightarrow$ `GX013851` $\rightarrow$ `GX013852` $\rightarrow$ `GX013853` $\rightarrow$ `GX013855` $\rightarrow$ `GX013856`.
5. **Non-Overlapping Cursors**: Within multi-clip sources (e.g. `GX013849` and `GX013855`), each clip's start time strictly advances past the previous clip's end time.

---

## Conclusion

By merging artificial candidate chunks within continuous footage, eliminating sub-millisecond floating-point precision rejections, and recalibrating surplus quota weighting beyond a guaranteed 1-clip floor, Journey Mode reliably features every usable recorded moment while preserving strict forward-chronological ordering and exact musical beat sync.
