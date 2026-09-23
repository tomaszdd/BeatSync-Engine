# Max Clip Length Cap — Implementation Report

## What changed

| File | Change |
|---|---|
| `src/video_processor.py` | New `_split_long_gaps()` helper: inserts synthetic intermediate cut points into any beat-to-beat gap longer than `max_clip_seconds`, splitting it into the smallest number of equal sub-segments that each fit the cap (mirrors `_make_candidate_windows()`'s chunking approach in `video_analysis.py`, per the spec). Wired into `build_frame_aligned_cut_timeline()` (new `max_clip_seconds` parameter, applied to `raw_cut_times` before frame quantization) and threaded through `create_music_video()`. |
| `src/gui.py` | New `max_clip_seconds` numeric input ("⏱️ Max clip length (seconds)", blank/`None` default = uncapped) next to `min_subject_confidence`, plumbed through `DEFAULT_SETTINGS`/session persistence/the render call, same path as `edge_buffer_seconds`. |
| `src/ui_content.py` | `LABEL_MAX_CLIP_SECONDS`/`INFO_MAX_CLIP_SECONDS`. |

No files were deleted. `_to_delete/` was not touched. The render plan (`clip_plan.py`) doesn't need to know about `max_clip_seconds` itself — like `edge_buffer_seconds`, its *effect* is already baked into the concrete `clips` array a render produces, so a saved plan replays correctly without re-reading the setting.

## Where the cap is enforced, and why there

The spec names `_build_boundaries()`/`_make_candidate_windows()` (`video_analysis.py`) as the machinery to reuse. Those specific functions chunk *source-video scene windows* for candidate scoring -- a different concept from the *beat-to-beat output segment timeline* this bug is actually about. I read this as "reuse the same chunking **pattern** those functions use" rather than literally calling them: `build_frame_aligned_cut_timeline()` in `video_processor.py` is the actual single place `segment_durations` gets computed from `beat_times`, so that's where I applied the identical split-into-equal-sub-chunks algorithm, on `raw_cut_times` before frame quantization.

This one insertion point automatically covers **both** cases the spec calls out:
1. A sparse beat-to-beat gap -- directly, since `raw_cut_times` is built straight from consecutive beats.
2. "held-shot segment under Journey/Chronological mode when footage runs out" -- indirectly: Journey mode's hold-tail mechanism (`JOURNEY_MAX_HOLD_SEGMENTS` in `stage6_av_planner.py`) extends a clip across whatever `segment_durations` it's handed; since those durations are already capped by construction once `max_clip_seconds` is set, the hold mechanism can never produce an overlong held segment either, with no changes needed in `stage6_av_planner.py` at all.

I did not build a parallel segment-splitting path; profiles/candidates/scoring downstream (`_build_segment_profiles`, `_choose_and_materialize_candidate`, etc. in `stage6_av_planner.py`) are completely unaware a segment is synthetic -- each sub-segment is scored and selected exactly like any other beat-aligned segment, per the spec's explicit requirement.

## Verification (real hardware, real data)

Per the task's instruction, this was reproduced against the actual render that surfaced the bug rather than a fresh scenario: `output/music_video_20260922_171820.plan.json`'s own `beat_times` (190 real detected cuts from a real 342s track) and, separately, a full render on `um890` through the exact same GoPro folder used for the subject-detection testing (`D:\Photos\GoPro\2025-10-01 Tereska Birth`, 15 files) with the same audio track as the original bug report.

**Confirmed the bug's own diagnosis first**: that track's real gaps are `max=3.785s, min=0.464s, mean=1.805s` -- genuinely dense, matching the spec's own note that this specific render "never needs it." So exercising the cap meaningfully requires either a sparser track or a cap tighter than that natural max; I used the latter (see below), since it lets me test directly against the exact real beat data that produced the original bug report rather than constructing a synthetic track.

**Direct algorithmic check** (`build_frame_aligned_cut_timeline()` called directly against the real 190-beat grid, `python` on `um890`):
- `max_clip_seconds=None` and `max_clip_seconds=0` produce **byte-identical** `cut_times`/`segment_frames` arrays to each other -- confirmed uncapped behavior is truly unaffected, not just "close."
- Sweeping `max_clip_seconds` = 2.0s / 1.0s / 0.5s (all tighter than the track's natural 3.785s max gap, to force splitting broadly) against the same real beat grid: segment count scales as expected (190 → 216 → 397 → 737), **every resulting segment duration respects the cap** (checked to within one frame of fps-quantization slack), and **total duration is preserved exactly** (`342.133s` in all cases, matching `audio_duration`) -- no drift introduced by the extra quantization pass.

**Full end-to-end render**, `max_clip_seconds=3.0` (tighter than the real track's 3.785s natural max gap, so splitting is actually exercised, not a no-op), all 15 real GoPro source videos, real AMF hardware encode: succeeded, 214 clips (up from the 190-clip uncapped baseline), 3840x2160 output. Inspecting the resulting `.plan.json` directly:
- **`max(final_duration) = 2.567s`** -- under the 3.0s cap, confirming the real materialized clip durations (not just the timeline math) respect the setting.
- **Zero clips** where `final_duration != source_duration` -- confirms the fix is genuinely "more/shorter clips," not time-stretching, matching the spec's own framing of the bug ("clip stretched to the music" was the perceived effect of one long *held* shot, not literal time-remapping).
- **Total `final_duration` across all 214 clips = 347.267s**, matching the `347.27s` audio duration -- no drift through the real pipeline either.

## Notes / judgment calls

- `max_clip_seconds` is not exposed on the CLI (`video_processor.py`'s `argparse` section), only the GUI, matching the spec's explicit file list (which lists `gui.py` in three places, not the CLI). The CLI path is unaffected either way since the new parameter defaults to `None` (uncapped).
- Like `min_subject_confidence`, `max_clip_seconds` is not written into `clip_plan.build_render_plan()`'s saved metadata -- see "What changed" above for why that's safe.

## Syntax check

```
python3 -c "
import ast
for f in ['src/video_processor.py','src/gui.py','src/ui_content.py']:
    ast.parse(open(f).read()); print(f, 'OK')
"
```
All three touched files parsed cleanly.
