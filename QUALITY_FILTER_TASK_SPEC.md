# Task: Add a black-frame / motion-blur quality filter to clip candidate scoring

## Bug, confirmed on real footage

The subject-detection pipeline (`src/subject_detection.py`, `src/gopro_telemetry.py`,
`src/auto_mode/stage5_qwen_scene_worker.py`) answers "is a subject visible" but nothing in the
pipeline checks "is this frame actually usable" independent of that. Two confirmed real examples
from `music_video_v3_chrono_20260923_103347.mp4` (rendered from
`D:\Photos\GoPro\2025-10-01 Tereska Birth\` on `um890`, `ssh um890`):

1. **`GX013854.MP4` around source time ~17.2s** (timeline clip idx=7, t=15.47-17.40 in the v3
   render) — the frame is **near-total black** (extracted via
   `ffmpeg -ss 16 -i <output.mp4> -frames:v 1 thumb_16s.jpg` on the render, confirmed by eye:
   solid black with only a faint reddish glow at one edge). Tagged only `['flow']` — nothing
   flagged it as unusable.
2. **`GX013856.MP4` around source time ~47.2s** (timeline clip idx=10, t=21.10-22.90) — the frame
   is **severely motion-blurred** (camera whip-panning past a ceiling light, human figures reduced
   to unrecognizable smears, extracted the same way as `thumb_22s.jpg`). Layer 2 (Qwen) actually
   tagged this **`['beauty', 'clean', 'filler', 'neutral', 'soft']`** — `beauty`/`clean` are wrong
   for a frame this blurred, meaning the semantic tagging pass didn't catch it either.

Both clips made it into the final chronological/journey render at `min_subject_confidence=0.3`
because "no subject visible" and "unusable due to darkness/blur" are different failure modes —
raising subject-confidence threshold doesn't address either root cause.

## What to do

1. Read `src/subject_detection.py` (the existing Layer 0/1 no-subject scoring:
   `score_subject_confidence()`, `_no_subject_score()`, the telemetry-based orientation/jerk
   signals) and `src/video_analysis.py`'s `analyze_video_sources()` (where the per-candidate
   "visual library" entries get their `action`/`beauty`/`quality` scores — note Stage 5's own log
   line already reports an aggregate `quality=0.48` style score across the library, so *some*
   quality signal may already exist somewhere in the pipeline; check whether it's real/wired to
   anything or just a shown-but-unused stat).
2. Add two lightweight, deterministic (non-LLM) per-frame checks, computed the same cheap way the
   existing telemetry/jerk checks are (sampled frames, not full-video passes):
   - **Darkness**: mean pixel luminance below a threshold (near-black frame, e.g. camera briefly
     obstructed, in a dark room, or a bad exposure moment) — should catch example 1 above.
   - **Blur**: a standard sharpness measure (e.g. variance of Laplacian, or an equivalent cheap
     metric already available via `cv2`/`numpy` if the repo already depends on OpenCV — check
     `requirements.txt`/imports first rather than adding a new heavy dependency) below a threshold
     — should catch example 2 above.
3. Wire these into the same exclusion path `min_subject_confidence`/`filter_no_subject_candidates()`
   already uses (`src/subject_detection.py`, referenced from `stage6_av_planner.py` per the
   earlier `SUBJECT_DETECTION_TASK_SPEC.md`/`SUBJECT_DETECTION_REPORT.md` in this repo — read those
   for the established pattern and naming conventions) so a genuinely-black or genuinely-blurred
   candidate gets excluded regardless of subject-confidence score, the same way a confirmed
   pointed-down/no-subject candidate already does. Don't gate this behind a new GUI slider unless
   trivial to add — a sensible always-on default threshold is fine, but pick thresholds
   conservatively (see "don't regress" below) and say what you picked and why in your report.
4. **Don't regress the existing behavior documented in `SUBJECT_DETECTION_REPORT.md`**: it
   explicitly notes fast handheld pans across a *real* subject can trigger a high jerk score and
   must NOT be excluded (jerk alone is weighted 0.7x for exactly this reason). Your blur check
   must not become a blanket "any camera motion excludes the clip" rule — target only genuinely
   unusable (can't-tell-what-it-is) frames, not merely non-static ones. Use the two confirmed real
   examples above as your "must exclude" cases, and re-use a couple of the report's own confirmed
   "correctly kept" examples (fast pan across a person carrying a car seat, `GX013845`/`GX013846`
   area — see `SUBJECT_DETECTION_REPORT.md`) as "must NOT exclude" regression cases.

## Verification (real hardware — required)

On `um890` (venv python: `C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe`, app
root `C:\BeatSyncTest\app\BeatSync-Engine-main`, test footage
`D:\Photos\GoPro\2025-10-01 Tereska Birth\`, backend model files already present at `bin/models/`
+ `bin/llama-bin-win-vulkan-x64/`, trimmed 120s audio at `C:\BeatSyncTest\audio_120s.mp3`, and the
video-analysis cache at `input/video_analysis_cache/` already warm from prior verified runs — see
`VIDEO_ANALYSIS_CACHE_FIX_REPORT.md` for how caching now works; re-renders against these same
source files should now complete in under two minutes, not 40+):

- Re-run `gui.process_video()` against the same footage and confirm the two specific candidates
  above (`GX013854` ~17s, `GX013856` ~47s) are now excluded from the visual library / never
  selected as clips.
- Confirm at least one of the report's "correctly kept" fast-pan-across-a-real-subject examples is
  still kept (not over-filtered).
- Extract a thumbnail from the new render's equivalent moments (or from the excluded candidates
  directly) to double check by eye, same technique as the two thumbnails described above.

## Constraints

- Primarily touch `src/subject_detection.py` / `src/video_analysis.py` / `src/gopro_telemetry.py`
  as relevant — if the real fix point is elsewhere, fix it there and say why.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `QUALITY_FILTER_REPORT.md` in the repo root (same tone/detail as
  `SUBJECT_DETECTION_REPORT.md`/`VIDEO_ANALYSIS_CACHE_FIX_REPORT.md` in this repo).
- Commit and push to `origin/main` when done and verified.
