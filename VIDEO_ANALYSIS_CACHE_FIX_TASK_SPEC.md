# Task: Fix video-analysis cache miss in `src/video_analysis.py`

## Bug

`analyze_video_sources()` in `src/video_analysis.py` is supposed to cache per-source-video
visual/Qwen analysis results under `input/video_analysis_cache/` (see `_cache_path()`,
`_load_cache()`, `_save_cache()`, and the loop around line ~296-319 that calls
`_load_cache(cache_file, require_ai=ai_available)` and prints
`f"   Reusing cached visual analysis {idx}/{len(existing)}: {_safe_name(video_file)}"` on a hit).

In practice it never hits. Two full real-hardware runs were made against the **exact same 15
source video files** (`D:\Photos\GoPro\2025-10-01 Tereska Birth\*.MP4` on the `um890` test box,
reachable via `ssh um890`, a Windows machine — this repo's own real-hardware test target per
`AMD_AMF_REPORT.md`/`SUBJECT_DETECTION_REPORT.md`), both with the Qwen/llama.cpp backend present
and enabled (`bin/models/Qwen3VL-2B-Instruct-Q8_0.gguf` + `mmproj-Qwen3VL-2B-Instruct-F16.gguf` +
`bin/llama-bin-win-vulkan-x64/llama-server.exe`+`llama-mtmd-cli.exe` all present under
`C:\BeatSyncTest\app\BeatSync-Engine-main\bin\`). Both runs:

- Took ~2566-2607 seconds for Stage 5 (the Qwen analysis stage) — i.e. the full cost both times.
- Printed near-identical `Qwen tags: 49/235 in ...s` — i.e. it redid the same work, not skipped it.
- Printed **zero** `Reusing cached visual analysis` lines.
- The cache directory `C:\BeatSyncTest\app\BeatSync-Engine-main\input\video_analysis_cache\`
  already had **132 files** in it before the second run (written by the first run), confirming
  `_save_cache()` does write files — the miss is on the **read/match** side, not that nothing
  gets saved.

The two runs differed only in caller-supplied parameters that should have **no bearing** on
per-source-video analysis caching: `output_filename`, `clip_order_mode` (`'auto'` vs
`'chronological'`), `min_subject_confidence` (`0.0` vs `0.3`), and the **audio file** (full track
vs a 120s-trimmed copy — audio is separate from per-video visual analysis and per the code's own
design the cache key is `_cache_path(video_file, enable_ai, qwen_model_path)`, i.e. audio isn't a
cache-key input at all).

## What to do

1. Read `_cache_path()`, `_load_cache()`, `_save_cache()`, and the calling loop in
   `analyze_video_sources()` (`src/video_analysis.py`) closely. Also read `_resolve_qwen_backend_paths()`
   and `_qwen_backend_model_path()` (same file, ~line 65-110) since `qwen_model_path` is a cache-key
   input and may be getting resolved to a different string on each call (e.g. relative vs absolute
   path, a session-specific temp path, or something non-deterministic like a timestamp/PID baked
   into a signature token) even though the underlying model file is identical.
2. Reproduce directly on `um890` (don't just read code — this bug was only found by actually
   running it twice; syntax-checking alone won't show it). The existing 132-entry cache from the
   real runs above is still present at
   `C:\BeatSyncTest\app\BeatSync-Engine-main\input\video_analysis_cache\` — **reuse it, don't wipe
   it**, so your verification run is cheap. A minimal repro:
   ```
   cd C:\BeatSyncTest\app\BeatSync-Engine-main
   # venv python: C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe
   ```
   then call `gui.process_video()` (see the two prior invocations in this repo's git history /
   `SUBJECT_DETECTION_REPORT.md` for the exact call shape) with `video_folder_path=r'D:\Photos\GoPro\2025-10-01 Tereska Birth'`
   and the AI backend present (it already is, at the paths above) — a pre-trimmed 120s audio file
   is already sitting at `C:\BeatSyncTest\audio_120s.mp3` if you want a fast end-to-end run rather
   than the full ~5.8min track.
3. Find the actual root cause (don't guess-patch). Print/log the cache path being checked and the
   cache path that was written by the prior run, side by side, if that's the fastest way to see the
   mismatch.
4. Fix it so that identical source video files + identical AI-backend-availability state produce a
   cache **hit** on a subsequent run, regardless of unrelated params like `clip_order_mode`,
   `min_subject_confidence`, `output_filename`, or which audio file is used.
5. Don't break correctness while fixing this: a cache entry must NOT be reused if the underlying
   source video file actually changed (content), or if the AI backend/model genuinely changed
   (e.g. `enable_ai` toggled, or a different Qwen model file swapped in) — those must still produce
   a fresh analysis. If your fix touches the signature/hash inputs, sanity-check this distinction
   explicitly and say so in your report.
6. The existing 132 cache files were written by the *old* (buggy) key scheme. If your fix changes
   the key format, they'll become orphaned dead weight rather than magically matching — that's
   fine (they're disposable, `input/video_analysis_cache/` is not source-controlled), but say so
   in your report rather than silently leaving stale files around or deleting them without saying.

## Verification (real hardware — required, do not skip)

On `um890`, after your fix: run `gui.process_video()` again against the same 15 source files with
AI enabled (reusing the existing cache from the runs described above, or a fresh one your own test
run produces — your choice, but state which). Confirm via the run's stdout:
- `Reusing cached visual analysis N/15: <filename>` appears for sources whose analysis is already
  cached — ideally all 15, proving the fix actually works end-to-end, not just in a unit test.
- Stage 5 completes in a small fraction of the ~2566s it took uncached (no full Qwen re-run).
- The resulting `Qwen tags: X/Y in Zs` line reflects genuinely skipped work (Z should collapse
  toward the cost of just the *uncached* portion, if any, not the full candidate pool).

Then also verify the **negative case** isn't broken: pick one source video, either touch/modify it
trivially (or reason carefully about the cache key and construct an equivalent proof) to confirm a
genuinely-changed source does NOT wrongly reuse a stale cache entry. Explain how you verified this
in your report — don't just assert it.

## Constraints

- Only touch `src/video_analysis.py` (and this spec file's own report, see below) unless you find
  the actual bug lives elsewhere (e.g. in how `gui.py`/`video_processor.py` pass `qwen_model_path`
  through) — if so, fix it at the real root cause and say why in your report.
- No deletions of anything outside the disposable `input/video_analysis_cache/` cache directory,
  and even there, only clear it if genuinely needed to isolate the bug (say so if you do).
- Write your findings and verification results to `VIDEO_ANALYSIS_CACHE_FIX_REPORT.md` in the repo
  root (same pattern as `AMD_AMF_REPORT.md`/`SUBJECT_DETECTION_REPORT.md`/`MAX_CLIP_LENGTH_REPORT.md`
  in this repo — read one of those for the expected tone/detail level).
- Commit your fix (with a clear message) and push to `origin/main` when done and verified.
