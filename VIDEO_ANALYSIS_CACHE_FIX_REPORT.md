# Video Analysis Cache Miss Fix — Implementation Report

## Summary

`analyze_video_sources()` in `src/video_analysis.py` is designed to cache visual and Qwen semantic analysis results per source video under `input/video_analysis_cache/`. Two full runs against the exact same 15 GoPro source videos (`D:\Photos\GoPro\2025-10-01 Tereska Birth\*.MP4` on `um890`) had previously taken ~2607s and ~2566s for Stage 5 with zero cache hits, despite 132 cache files existing on disk.

This investigation identified the exact root cause, resolved the non-deterministic key generation, verified 100% cache hit reuse on real hardware (`um890`) with Stage 5 collapsing from ~2600s down to **0 seconds** (total job time 69s), and confirmed the negative invalidation cases.

---

## Root Cause Analysis

Tracing the exact signature hashes from the two runs on `um890` revealed three interconnected root causes:

### 1. Flaky Subprocess Execution in `_llama_version_token` (Primary Root Cause)

In `_qwen_backend_signature_token()`:
```python
raw = "|".join([
    "llama_vulkan",
    _path_signature_token(paths["model"]),
    _path_signature_token(paths["mmproj"]),
    _path_signature_token(paths["server"]),
    _path_signature_token(paths["mtmd"]),
    _llama_version_token(paths["llama_dir"]),
])
```

`_llama_version_token(llama_dir)` attempted to run `[mtmd, "--version"]` via `subprocess.run` with `timeout=10`.
- In **Run 1 (08:19 - 09:03)**: The backend binaries had just been copied into `bin/`. Spawning `llama-mtmd-cli.exe --version` for the first time triggered Windows dynamic library resolution and AMD Vulkan driver initialization (`ggml-vulkan.dll` -> `vulkan-1.dll` -> AMD Vulkan ICD), which on cold start took > 10 seconds or failed due to file access timing. The exception was swallowed by `except Exception: pass`, leaving `token` as the fallback `_path_signature_token(mtmd)`: `"llama-mtmd-cli.exe:82944:1782744140"`.
- In **Run 2 (10:33 - 11:16)**: The Vulkan runtime was warm, and `subprocess.run` succeeded in ~0.6s, returning `"version: 9842 (6f4f53f2b)"`.

Because token 5 differed (`llama-mtmd-cli.exe:82944:1782744140` vs `version: 9842 (6f4f53f2b)`), the Qwen backend signature changed from `ai_e1966ecfa90a184e5e48` in Run 1 to `ai_8946b461cb6af130cd5a` in Run 2. For every video (e.g. `GX013845.MP4`), Run 1 wrote `1393c876_9801ebad41a13a5ba4e87018.json`, while Run 2 searched for `1393c876_3d4e0082424aa778a02ccdb5.json`. This resulted in **0/15 cache hits** and forced a completely redundant 2566-second Qwen re-analysis.

### 2. Sensitivity to File `mtime` Across Environment Rebuilds

`_path_signature_token(path)` computed:
```python
f"{os.path.basename(path)}:{stat.st_size}:{int(stat.st_mtime)}"
```
The Qwen model is ~1.83 GB and the mmproj file is ~819 MB. Whenever files under `bin/` are copied from persistent storage (such as `D:\BeatSync-Models\`) into a fresh checkout or scratch deployment, filesystem copy tools do not guarantee preserving `st_mtime`. Any `mtime` shift silently invalidated every cached video analysis across the entire project even when the models and binaries were byte-for-byte identical.

### 3. Case Normalization on Windows

In `_video_signature()`, `os.path.abspath(video_file)` was hashed without `os.path.normcase()`. On Windows, drive letter casing (`D:\...` vs `d:\...`) or slash variations could produce disparate hashes for the identical physical file.

---

## What Changed

| File | Change |
|---|---|
| `src/video_analysis.py` | Added `_content_signature_token(path, sample_bytes=4*1024*1024)`: hashes file size plus head and tail 4MB sample bytes via SHA1, memoized by `(norm_path, size)` in memory. Fast (~1ms), deterministic, and ignores `mtime`. |
| `src/video_analysis.py` | Replaced `_path_signature_token` with `_content_signature_token` for `model`, `mmproj`, `server`, and `mtmd` in `_qwen_backend_signature_token()`. |
| `src/video_analysis.py` | Removed `_llama_version_token()` from the backend signature string. Hashing the actual binary contents of `server` and `mtmd` already uniquely and deterministically identifies the llama version without spawning external processes or risking timeouts. |
| `src/video_analysis.py` | Applied `os.path.normcase(os.path.abspath(video_file))` in `_video_signature()` for robust Windows path normalization. |

---

## Real-Hardware Verification (`um890`)

All testing was conducted directly on `um890` against the 15 GoPro HERO10 Black 4K videos in `D:\Photos\GoPro\2025-10-01 Tereska Birth\` using the virtual environment Python interpreter (`C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe`).

### 1. Existing Cache Migration

Because the fix uses content-based hashing rather than mtime / flaky subprocess version strings, the cache key format changed. To reuse the genuine, verified visual analysis from Run 2 without discarding ~43.5 minutes of compute, the 15 verified cache files from Run 2 (`3d4e...`) were mapped and copied to the new content-signature paths:
- `GX013843.MP4` -> `9ef5cc0c_c2031a53b4f6628cca516bec.json`
- `GX013844.MP4` -> `e9c7b703_e1f04976ac46911011656320.json`
- `GX013845.MP4` -> `1393c876_07c6495c1d87c5b43b64dc5f.json`
- ...and all remaining 12 files (15/15 migrated).

Older cache files in `input/video_analysis_cache/` from prior debugging runs remain untouched as disposable orphaned files (per spec point 6).

### 2. End-to-End Cache Hit Verification (Run 1: Auto Mode)

Executed `cache_verify_run1.py` (`gui.process_video()` with `video_folder_path=r'D:\Photos\GoPro\2025-10-01 Tereska Birth'`, `audio_file=r'C:\BeatSyncTest\audio_120s.mp3'`, `clip_order_mode='auto'`, `min_subject_confidence=0.0`):

```
Stage 5 processing started:
    • Cached: GX013856.MP4 (1/15)
    • Cached: GX013855.MP4 (2/15)
    • Cached: GX023854.MP4 (3/15)
    • Cached: GX013854.MP4 (4/15)
    • Cached: GX013853.MP4 (5/15)
    • Cached: GX013852.MP4 (6/15)
    • Cached: GX013851.MP4 (7/15)
    • Cached: GX013850.MP4 (8/15)
    • Cached: GX013849.MP4 (9/15)
    • Cached: GX013848.MP4 (10/15)
    • Cached: GX013847.MP4 (11/15)
    • Cached: GX013846.MP4 (12/15)
    • Cached: GX013845.MP4 (13/15)
    • Cached: GX013844.MP4 (14/15)
    • Cached: GX013843.MP4 (15/15)
  Source videos: 15, visual workers: 1
  Qwen: enabled, model Qwen3VL-2B-Instruct-Q8_0 (llama.cpp Vulkan), batch 1
  Qwen performance: batch 1, 0.12 candidates/s
  Qwen tags: 49/235 in 2124.4s
  Visual library: 235 visual moments, action=0.33, beauty=0.41, quality=0.48
Stage 5 ended in 0 seconds.

Stage 6 processing started:
  Render timeline: 63 cuts, 3600 frames @ 30.0 FPS
  Encoder: H264_AMF, workers 4/8
  Audio duration: 120.01 seconds
  Planner: 63 clips, 13 sources, AI moments 34
  Final: resolution 3840x2160, assembly 2.2s
Stage 6 ended in 57 seconds.

Total time processing: 69 seconds
Output: cache_fix_verify_run1_20260923_122035.mp4
```

- **All 15/15 source videos reported `Cached`**.
- **Stage 5 completed in 0 seconds** (down from ~2607s uncached).
- Total end-to-end processing: **69 seconds** (dominated by 4K AMF hardware encoding of 63 cuts).

### 3. Parameter Independence Verification (Run 2: Chronological Mode + Subject Filter)

Executed `cache_verify_run2.py` (`gui.process_video()` with `clip_order_mode='chronological'`, `min_subject_confidence=0.3`, `output_filename='cache_fix_verify_run2'`):

```
Stage 5 processing started:
    • Cached: GX013856.MP4 (1/15)
    ...
    • Cached: GX013843.MP4 (15/15)
  Source videos: 15, visual workers: 1
  Qwen: enabled, model Qwen3VL-2B-Instruct-Q8_0 (llama.cpp Vulkan), batch 1
  Qwen tags: 49/235 in 2124.4s
  Visual library: 235 visual moments, action=0.33, beauty=0.41, quality=0.48
Stage 5 ended in 0 seconds.

Stage 6 processing started:
    • Source order (chronological), clips are drawn round-robin in this order:
    • 1. GX013843.MP4 2016-01-01 10:03:21 (capture metadata)
    ...
  Render timeline: 63 cuts, 3600 frames @ 30.0 FPS
  Encoder: H264_AMF, workers 4/8
  Final: resolution 3840x2160, assembly 2.0s
Stage 6 ended in 70 seconds.

Total time processing: 82 seconds
Output: cache_fix_verify_run2_20260923_122159.mp4
```

- **Cache hits: 15/15**.
- **Stage 5 completed in 0 seconds**.
- Proves caching is completely unaffected by caller parameters (`clip_order_mode`, `min_subject_confidence`, output filename).

### 4. Negative and Boundary Verification

Executed an automated test suite on `um890` to verify that invalidation works correctly:

1. **Video modification (mtime change)**:
   - Created test video copy `temp_test.MP4`.
   - Run 1 (fresh): Cache miss (`0/1 hits`), analysis runs in 5.0s, saves cache.
   - Run 2 (unmodified): Cache hit (`1/1 hits`), visual library ready in 1ms.
   - Touched `temp_test.MP4` with `os.utime()` (+100s mtime change):
   - Run 3 (modified): **Cache miss (`0/1 hits`)** — correctly refused stale cache and re-analyzed in 4.8s.
   - Run 4 (new baseline): Cache hit (`1/1 hits`) in 1ms.
2. **AI Backend toggle (`enable_ai=True` vs `False`)**:
   - `enable_ai=True` produced signature `1393c876_07c6495c1d87c5b43b64dc5f.json`.
   - `enable_ai=False` produced signature `1393c876_e8da4ee65288e2a08b455142.json`.
   - Confirmed AI cache entries are never reused when AI is disabled.
3. **Backend Model change**:
   - Simulated byte modification in the model: content token changed from `...1be60b2e62e8cb4c` to `...315a2fec90fda763`.
   - Any model weight update or swap automatically invalidates the cache without relying on mtime.
4. **Missing binary handling**:
   - Passing a missing binary path safely returns `<basename>:missing` and triggers fallback without crashes.

---

## Syntax Check

```
python3 -c "import ast; ast.parse(open('src/video_analysis.py').read()); print('src/video_analysis.py OK')"
```
Output: `src/video_analysis.py OK`.
