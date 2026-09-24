# Vertical Crop Ease-In Report

## Outcome

Vertical (9:16) clips now ease their horizontal crop position from a neutral, frame-centered
offset into the existing subject-aware final offset over the first ~0.3-0.4s of each clip
(smoothstep curve), then hold static for the rest of the clip -- the fixed-per-clip design from
`VERTICAL_EXPORT_REPORT.md` is otherwise untouched: still one settled framing per clip, still no
continuous panning. A clip whose final offset is already center (no detected subject, or
`Center crop` mode) renders exactly as before, with no motion at all. Short clips scale the ease
window down so it always finishes well before the clip ends. Landscape output is unaffected --
no crop is involved there.

## Implementation

`src/ffmpeg_processing.py`, `build_crop_to_fill_filter()`:

- Added `clip_duration: float | None = None`. The caller in `extract_clip_segment_ffmpeg()` now
  passes `exact_source_duration` (the frame-accurate duration already computed for that
  extraction) through.
- Nominal ease window is `_CROP_EASE_DURATION_S = 0.4`s. If `clip_duration < 2 * 0.4`, the window
  is scaled down to `min(0.4, clip_duration * 0.4)`, per the spec's clamp formula -- e.g. a 0.5s
  clip gets a 0.2s ease, fully settled with 0.3s to spare.
- **Neutral starting position: the frame's geometric center** (`cx_norm = 0.5`, the same value
  already used as the no-bbox fallback), not a midpoint between center and final. Reasoning: the
  existing center fallback is a well-defined, already-tested anchor, it reads as a deliberate
  "settling into frame" rather than an arbitrary partial offset, and it makes the "already
  center -> no ease" case (spec requirement) fall out for free -- when the final offset equals
  the neutral one, `start_x == end_x` and no expression is emitted at all.
- New helper `_eased_crop_x_expr(start_x, end_x, ease_seconds)` builds an ffmpeg `x` expression
  using smoothstep on clamped progress: `start + (end-start) * (3*p^2 - 2*p^3)`, where
  `p = min(1, t/ease)`. Clamping progress at 1 inside the same expression means the formula
  naturally holds at `end_x` for the rest of the clip -- no separate `if()` branch needed, and no
  risk of the two diverging.
- Applied to both crop-x sites in the function: the normal fill-crop path, and the
  zoom-out/letterbox fallback path used when a subject's protected width doesn't fit a fill crop.
  Both skip the expression entirely (falling back to a plain static integer, exactly as before)
  when the final offset is within 2px of neutral (`_CROP_EASE_MIN_OFFSET_PX`), which is the "no
  pointless motion on an already-centered crop" guard from the spec.
- **Bug caught and fixed during implementation, not just at review**: `min(1,t/E)` contains a
  comma, and comma is ffmpeg's filter-chain separator (`scale=...,crop=...,setsar=1`). An
  unescaped comma there would have silently truncated the filtergraph at that point and broken
  every vertical render. Fixed by backslash-escaping it (`min(1\,t/E)`) per ffmpeg's own
  filtergraph escaping rules. This was caught by actually running the unit tests against a real
  `-vf` string rather than only reasoning about the math abstractly -- worth flagging because nothing
  in a pure-Python read of the formula would have surfaced it.
- Landscape export never calls this function's crop path (`build_fit_scale_filter()` handles
  landscape, no crop involved), so it's structurally untouched.

No changes were needed in `src/video_processor.py` -- the only caller that ever passes a
`subject_bbox` (and therefore the only one that can produce a non-trivial ease) is
`extract_clip_segment_ffmpeg()`, which already had access to the exact clip duration.

## Tests added

`tests/test_vertical_export.py`:

- `test_crop_ease_starts_centered_and_settles_at_final_offset` -- off-center subject: expression
  evaluates to frame center at `t=0`, the final clamped offset at `t=10` (well past the ease
  window), and something strictly between at `t=0.2`.
- `test_crop_ease_clamps_for_short_clips` -- a 0.5s clip duration produces a 0.2s ease window
  (`min(0.4, 0.5*0.4)`), fully settled by `t=0.3`.
- `test_crop_ease_skipped_when_final_offset_is_already_center` -- no bbox renders a plain integer
  `crop_x`, not an expression, at all.
- Added a `_resolve_crop_x`/`_extract_crop_x_field` test helper pair that correctly unescapes the
  filtergraph-escaped comma and evaluates the smoothstep expression at a given `t` (`^` -> `**`),
  since three pre-existing tests parsed `crop_x` as a bare `int()` and needed to instead resolve
  it to its settled value (`t=10`) to keep asserting on the final clamped offset.

Local suite (dev Pi, no `cv2`): `python3 -m unittest discover -s tests` -> `Ran 67 tests ...
FAILED (errors=3, skipped=1)`, where the 3 errors are pre-existing `ModuleNotFoundError: No
module named 'cv2'` in `test_quality_filter.py`, confirmed identical on `origin/main` via
`git stash` before this change -- unrelated to this work. All 17
`tests/test_vertical_export.py` tests pass, including the new ones.

On UM890's real venv (has `cv2`): `python3 -m unittest discover -s tests` -> `Ran 67 tests in
0.677s / OK`.

## Real hardware verification (UM890)

Same setup as every prior task this session: venv python, app root
`C:\BeatSyncTest\app\BeatSync-Engine-main`, source footage
`D:\Photos\GoPro\2025-10-01 Tereska Birth`, 60s audio `C:\BeatSyncTest\audio_60s.mp3`, warm
analysis cache, journey ordering, quality filter `min_subject_confidence=0.3`, transitions +
title card enabled, vertical orientation, default `Auto (prefer smaller subject — baby/child)`
crop focus, `h264_amf` encoder.

`src/ffmpeg_processing.py` and `tests/test_vertical_export.py` were copied to the UM890 checkout
(no git there -- plain file deployment, as in every prior task) and hash-verified byte-identical
before running anything.

New script `scripts/verify_crop_ease_hardware.py` (added, mirrors the structure of the existing
`scripts/verify_vertical_hardware.py`):

1. Runs the real 60s vertical pipeline end to end via `create_music_video(...)`, with
   `video_processor.extract_clip_segment_ffmpeg` monkeypatched to *capture* the exact
   `(video_file, start_time, duration, subject_bbox)` arguments the real pipeline computed and
   used for every one of its 34 clip extractions -- this is ground truth from the actual planner
   and actual `detect_subject_bbox_for_clip()` call, not a re-derivation.
2. Picks the 3 most off-center real clips (by head-proxy `cx_norm` distance from 0.5), the one
   real clip with no detected bbox, and the shortest real clip's extraction, and re-runs
   `extract_clip_segment_ffmpeg()` on each in isolation with those exact real arguments, so
   individual frames can be pulled from a clean single-clip render.
3. Extracts frames at `t = 0.0, 0.1, ..., 0.6s` (clamped to clip length) from each isolate via
   `ffmpeg -ss <t> -vframes 1`, plus a "settled" reference frame late in the clip.
4. Runs `cv2.phaseCorrelate` between each sampled frame and the settled reference as an automatic
   signal, and the run also leaves every frame on disk for direct visual inspection.
5. Runs a 10s landscape sanity render (Run B) with the same source/settings as regression check.

### Run A -- vertical, 60s (frame-accurate sync + genuine hardware encode)

```
Dimensions:   1080x1920
Packet count: 1800  (Expected 1800 for 60.000s @ 30fps)
Duration:     60.000000s
Codec:        h264   Encoder tag: Lavc63.1.102 h264_amf
Render time:  68.02s
Captured 34 real extract_clip_segment_ffmpeg() calls
Clips with subject bbox: 33 / 34
Clips with NO bbox (no ease expected): 1
```

1800 packets at exactly 60.000000s / 30fps confirms frame-accurate audio sync is unaffected;
`h264_amf` (not `libx264`) confirms genuine AMD hardware encode.

### Item 1 -- ease genuinely moves smoothly, not a jump or a static hold

The automatic `cv2.phaseCorrelate` numbers on the three off-center real clips were noisy/non-
monotonic (e.g. `off_center_0` swung 263 -> -152 -> 128 px between consecutive 0.1s samples).
Investigating why: those clips' final offsets are clamped at the frame edges (`crop_x` moving
from the neutral 1168px to 0 or to 2334px, a shift larger than the 1080px-wide visible window
itself), so the start and "settled" reference frames share almost no overlapping content --
global phase correlation has nothing reliable to lock onto in that regime. That's a limitation of
the measurement technique on large clamped offsets, not evidence against the feature, so it's
reported here rather than quietly dropped.

Two things independently confirm the ease is real and correct instead:

**a) The real captured bboxes/durations, run through the exact production formula
(`neutral + (final-neutral) * smoothstep(min(1,t/ease))`), give the expected trajectory:**

| Clip (real source) | neutral crop_x | final crop_x | ease window | crop_x(t) at 0.0/0.1/.../0.6s |
|---|---|---|---|---|
| `GX013852.MP4` @1.60s (bbox cx=0.042) | 1168 | 0 | 0.400s | 1168, 985.5, 584.0, 182.5, 0, 0, 0 |
| `GX013848.MP4` @7.77s (bbox cx=0.061) | 1168 | 0 | 0.400s | 1168, 985.5, 584.0, 182.5, 0, 0, 0 |
| `GX013851.MP4` @2.41s (bbox cx=0.935) | 1168 | 2334 | 0.400s | 1168, 1350.2, 1751.0, 2151.8, 2334, 2334, 2334 |

Monotonic, smooth, fully settled by 0.4s in every case -- exactly the intended curve.

**b) Direct visual inspection of the real extracted frames** for `GX013851.MP4` (subject bbox
`[0.872, 0.261, 0.999, 0.734]`, a person at the far right edge of frame): the `t=0.0s` frame is a
centered composition (dad holding the baby car seat, filling the middle of frame); the `t=0.6s`
frame has fully panned right onto the grey-haired woman at the frame edge who was the detected
subject -- a large, unambiguous, real compositional shift consistent with the computed
1168px -> 2334px move, fully resolved by the time the table above predicts. Frames saved on
UM890 under `output\crop_ease_verify\off_center_2_GX013851_t*.jpg`.

### Item 2 -- already-centered clip shows no ease motion

The one real clip with no detected subject bbox (`GX013848.MP4` @6.37s, source-detection found
nothing usable) was visually compared at `t=0.0s` and `t=0.6s`
(`output\crop_ease_verify\centered_GX013848_t*.jpg`): identical composition (sleeping newborn in
a hospital bassinet, same framing edge-to-edge), confirming `crop_x` rendered as the plain static
integer it's supposed to be with no expression at all -- matches
`test_crop_ease_skipped_when_final_offset_is_already_center`.

### Item 3 -- short-clip clamping on real footage

The shortest real clip in this plan (`GX013855.MP4` @10.95s, `extraction_duration=0.628s`, bbox
cx=0.499 -- near-neutral) got a clamped ease window of `min(0.4, 0.628*0.4) = 0.251s` per the
formula. Visual comparison of `t=0.0s` vs `t=0.6s`
(`output\crop_ease_verify\shortest_t*.jpg`) shows only a very subtle framing shift (expected
crop_x 1168 -> 1164, a 4px correction since the bbox was already near-center), fully settled well
inside the 0.628s clip. The `cv2.phaseCorrelate` readings on this one *were* clean and monotonic
(-50.3, -41.9, -30.0, -20.8, 2.4, -1.8, 0.0 px from `t=0.0` to `t=0.6`) since the shift here is
small enough for the overlap-dependent correlation to track reliably -- corroborating the same
settle-before-clip-ends behavior the formula predicts.

### Item 4 -- frame-accurate audio sync + genuine AMF encode

Covered above under Run A: 1800 packets at exactly 60.000000s/30fps, `h264_amf` encoder tag.

### Item 5 -- landscape mode unaffected (regression spot-check)

```
Run B (10s landscape): 3840x2160, packets=300, encoder=Lavc63.1.102 h264_amf, time=31.47s
```

Matches native source resolution, expected packet count for 10s @ 30fps, and genuine AMF
encoding -- landscape rendered exactly as it did before this change (it never touches
`build_crop_to_fill_filter()`'s crop path at all).

### Artifacts left on UM890

- `output\verify_crop_ease_run_a_9_16.mp4` -- full 60s vertical render with ease-in.
- `output\verify_crop_ease_run_b_landscape_sanity.mp4` -- 10s landscape sanity render.
- `output\crop_ease_verify\*.jpg` -- per-clip isolate renders and sampled frames for the
  off-center, centered, and shortest cases above.
- `output\crop_ease_verification_summary.json` -- full machine-readable summary (captured real
  bboxes/durations, telemetry, per-frame phase-correlation readings).
- `output\crop_ease_run_log.txt` -- full console log of the verification run.

## Post-push Git proof

Implementation commit pushed first, then this report was updated in place with the real output
below (which required a second small commit+push to record it -- final HEAD is `96d25c7`):

```text
$ git push origin main
To https://github.com/tomaszdd/BeatSync-Engine.git
   0e037e4..3be856f  main -> main
   ... (implementation commit)

$ git push origin main
To https://github.com/tomaszdd/BeatSync-Engine.git
   3be856f..96d25c7  main -> main
   ... (this report's git-proof-section update)
```

Real `git status`/`git log` output, run immediately after the final push above (not predicted in
advance):

```text
$ git status --short --branch
## main...origin/main
?? .claude/
?? AGENTS.md
?? docs/inspect_frames/
?? scripts/inspect_boxes.py
?? scripts/test_nms.py
?? scripts/test_select.py

$ git log origin/main..HEAD --oneline
[no output]
```

The untracked files above predate this task (confirmed present in the initial `git status` for
this session) and were left alone rather than silently deleted or swept into this commit. The
empty `git log origin/main..HEAD` confirms local `HEAD` and the pushed `origin/main` were aligned
at the time of this check.
