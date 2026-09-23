# Black-Frame and Motion-Blur Quality Filter — Implementation Report

## Summary

In previous renders (such as `music_video_v3_chrono_20260923_103347.mp4` on `um890`), unusable clip candidates made it into final renders even when subject-detection filtering was enabled:
1. **`GX013854.MP4` around source time ~17.2s** (timeline clip idx=7 in v3 render): A **near-pitch black frame** (`mean luminance = 0.0138`, `Laplacian variance = 3.06`) caused by the camera being obstructed or in a pocket/bag.
2. **`GX013856.MP4` around source time ~47.2s** (timeline clip idx=10 in v3 render): A **severe motion-blur whip-pan smear** past a ceiling light (`Laplacian variance = 85.78`, with individual smear frames dropping to `14.3`). Qwen had hallucinated `['beauty', 'clean', 'soft']` with high visual quality based on a subsequent static frame in the chunk, overpowering telemetry jerk/orientation penalties.

"No subject visible" and "unusable frame due to pitch black or motion-blur smears" are fundamentally different failure modes. A high subject-confidence slider cannot fix them when models hallucinate or when YOLO detects false-positive objects.

This implementation introduces lightweight, deterministic (non-LLM) per-frame quality checks—mean luminance for darkness and variance of Laplacian for blur—integrated as an **always-on exclusion filter** in `filter_no_subject_candidates()` and candidate scoring.

Verified end-to-end on real hardware (`um890`) with warm analysis cache:
- 149 unusable candidates excluded across the library.
- Both confirmed bug targets (`GX013854` black frame, `GX013856` ~47s whip-pan) completely eliminated.
- Handheld fast pans across real subjects (`GX013855`, `GX013849`, `GX013845`, `GX013846`) safely preserved.
- Thumbnail metrics at t=16s and t=22s confirm dramatic quality improvements:
  - t=16s: `lum=0.0138`, `lap=3.06` (bug) $\rightarrow$ `lum=0.4030`, `lap=851.88` (fixed).
  - t=22s: `lum=0.4219`, `lap=85.78` (bug) $\rightarrow$ `lum=0.3960`, `lap=927.84` (fixed).
- Full render completed in 70.2 seconds on `um890`.
- All 9 unit tests passed in 0.015s.

---

## What Changed

| File | Change |
|---|---|
| `src/subject_detection.py` | Added constants `DEFAULT_MIN_LUMINANCE = 0.05` and `DEFAULT_MIN_LAPLACIAN_VAR = 65.0`. Added functions `score_frame_darkness()`, `score_frame_blur()`, `score_frame_quality()`, and `is_unusable_quality()`. Downscales frame samples to max-width 360px before calculating grayscale luminance and Laplacian variance. Includes legacy candidate fallback using telemetry jerk/orientation metrics when Laplacian variance is missing from older caches. |
| `src/video_analysis.py` | Updated `_measure_frame_samples()` (CPU fallback) and `_measure_frames_gpu()` (CuPy GPU acceleration) to compute `min_luminance`, `mean_luminance`, `min_laplacian`, and `mean_laplacian` across sampled frames. Threaded these four fields through `_build_candidate()` into visual library candidate dictionaries and cache serialization. |
| `src/auto_mode/stage6_av_planner.py` | Updated `_no_subject_score()` to evaluate `is_unusable_quality()`, immediately returning `1.0` (unusable dead shot) if flagged. Updated `filter_no_subject_candidates()` to run an always-on quality pre-filter pass: candidates failing darkness or motion-blur checks are excluded from the candidate pool regardless of `min_subject_confidence` (even when slider = 0.0 / off). Added debug logging for excluded candidate counts. |
| `tests/test_quality_filter.py` | **New.** 9 unit tests covering black frame luminance detection, normal frame luminance, blur vs sharp frame Laplacian variance, candidate darkness checks, motion-blur smear checks, legacy telemetry fallback, regression protection for legitimate handheld pans, `_no_subject_score()` scoring behavior, and `filter_no_subject_candidates()` always-on filtering. |

No files were deleted. Existing docstrings, comments, and public APIs were preserved.

---

## Threshold Selection and Rationale

The thresholds were calibrated against real GoPro HERO10 footage (`D:\Photos\GoPro\2025-10-01 Tereska Birth` on `um890`):

### 1. Darkness Threshold: `DEFAULT_MIN_LUMINANCE = 0.05` (~12.75 / 255)
- **Pocket / Covered Lens / Bad Exposure**: Frames from `GX013854` (t=0..17s) and `GX023854` have mean luminance ranging from `0.005` to `0.0138`.
- **Dimmest Usable Indoor Scene**: The dimmest usable indoor shots in the library (dim hospital room corners and shaded car interiors) have `min_luminance >= 0.074` and `mean_luminance >= 0.152`.
- **Decision**: Setting `DEFAULT_MIN_LUMINANCE = 0.05` creates a clear safety margin: it deterministically discards pitch-black obstructed/pocket shots while preventing false exclusions on genuine low-light indoor footage. In addition, an edge-case guard flags frames where `min_luminance < 0.03` if `mean_luminance < 0.08`.

### 2. Sharpness Threshold: `DEFAULT_MIN_LAPLACIAN_VAR = 65.0` (max-360px scaled)
- **Whip-Pan Blur Smear**: During camera transitions, rapid drops, or whip-pans past lights (e.g. `GX013856` ~47.2s), frames degenerate into horizontal streaks. Laplacian variance on 360px-downscaled frames drops to `14.3 - 60.3`.
- **Legitimate Fast Handheld Motion (Regression Check)**:
  - `GX013845.MP4` (walking in hospital): `min_laplacian = 929.7`
  - `GX013846.MP4` (corridor walking): `min_laplacian = 447.7`
  - `GX013855.MP4` (walking while carrying infant car seat): `min_laplacian = 75.9 - 88.6`
  - `GX013849.MP4` (outdoor walking across car park): `mean_laplacian = 2104.0`
- **Decision**: Setting `DEFAULT_MIN_LAPLACIAN_VAR = 65.0` on 360px-scaled frames cleanly distinguishes severe motion-blur smears (`< 60.3`) from active handheld camera movement across recognizable scenes (`>= 75.9`).

---

## Architectural Decision: Always-On Exclusion

Previously, `min_subject_confidence` defaulted to `0.0` (off), which bypassed `filter_no_subject_candidates()`. Furthermore, candidates with high YOLO subject confidence (0.95) or Qwen visual quality scores (0.9) could overwhelm telemetry penalties inside `_no_subject_score()`.

To ensure genuinely unusable footage is never selected:
1. `filter_no_subject_candidates()` now executes an always-on deterministic quality pass. Genuinely black or severely blurred candidates are excluded first, regardless of whether `min_subject_confidence` is 0.0 or higher.
2. `_no_subject_score()` also returns `1.0` when a candidate fails `is_unusable_quality()`, ensuring fallback scoring paths also discard unusable shots.
3. No new slider was added to the GUI: pitch-black and motion-blurred smears are objectively defective footage; an always-on conservative gate is the correct design.

---

## Real-Hardware Verification (`um890`)

### Verification Setup
- **Host**: Minisforum UM890 Pro (`um890`), AMD Ryzen 9 8945HS with Radeon 780M iGPU.
- **Python**: `C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe` (Python 3.12.10).
- **Test Footage**: `D:\Photos\GoPro\2025-10-01 Tereska Birth\` (15 GoPro HERO10 Black MP4 files, 19.4 minutes total).
- **Audio**: `C:\BeatSyncTest\audio_120s.mp3` (120s duration).
- **Settings**: `clip_order_mode='chronological'`, `min_subject_confidence=0.3`.

### 1. Unit Tests
Executed directly on `um890`:
```
C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe tests/test_quality_filter.py
Ran 9 tests in 0.015s
OK
```

### 2. Candidate Filtering Across Warm Analysis Cache
The 15 source files in `input/video_analysis_cache/` were evaluated through `is_unusable_quality()`:
- **Total candidates evaluated**: 1,847
- **Total unusable candidates excluded**: 149
  - Darkness (near-black pocket/obstructed frames): 134 candidates (including all 103 dead candidates in `GX013854` and early segments of `GX023854`)
  - Motion-blur smears: 15 candidates (including the ~47s whip-pan in `GX013856`)
- **Total usable candidates retained**: 1,698

### 3. End-to-End Render Execution
Ran `gui.process_video()` with the verified quality filter:
- **Stage 5 (Visual Analysis)**: 0.0s (15/15 cache hits via deterministic cache keys).
- **Stage 6 (AV Planner)**: Excluded 149 unusable candidates; selected 63 planned clips.
- **Stage 7 (Video Assembly)**: Rendered output `quality_filter_verify_20260923_131843.mp4` via AMD AMF (`h264_amf`) in 70.2 seconds total.

### 4. Verification of Specific Bug Targets
- **Target 1 (`GX013854` black frame at ~17.2s)**:
  - Previous render: selected as Clip 7 (timeline t=15.47 - 17.40s).
  - New render: **Completely eliminated.** `GX013854` appears 0 times in the entire 63-clip timeline.
- **Target 2 (`GX013856` ~47.2s whip-pan smear)**:
  - Previous render: selected as Clip 10 (timeline t=21.10 - 22.90s).
  - New render: **Completely eliminated.** The selected clips from `GX013856` are all sharp, stable segments (src=21.07s, 10.38s, 24.99s, 2.00s, 16.11s, 29.61s, 7.96s).

### 5. Regression Check: Handheld Motion Across Real Subjects
- `GX013855` (person walking carrying newborn car seat): Retained across 8 distinct timeline clips (src=98.02s, 108.71s, 102.96s, 87.18s, 38.79s, 63.95s, 67.96s, 79.50s).
- `GX013849` (walking outdoors in car park): Retained across 14 distinct timeline clips (src=31.11s, 52.15s, 87.48s, 7.02s, 67.44s, 18.24s, 73.28s, 79.08s, etc.).

### 6. Frame-by-Frame Thumbnail Verification

Thumbnails extracted from the rendered output at the exact problem timestamps:

| Timestamp | Old Render (Bug) | New Render (Fixed) | Visual Outcome |
|---|---|---|---|
| **t = 16.0s** | `lum = 0.0138`, `lap = 3.06` | `lum = 0.4030`, `lap = 851.88` | Replaced solid black frame with a bright, crisp clip |
| **t = 22.0s** | `lum = 0.4219`, `lap = 85.78` | `lum = 0.3960`, `lap = 927.84` | Replaced blurry ceiling light smear with a sharp, stable corridor shot |

---

## Conclusion

The quality filter cleanly and deterministically resolves the black-frame and motion-blur failure modes without adding LLM latency, without regressing genuine handheld motion, and without requiring manual slider adjustments by the user.
