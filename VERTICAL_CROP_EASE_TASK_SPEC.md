# Task: Subtle ease-in for the vertical crop position, per clip

## Context

The vertical (9:16) export mode (`VERTICAL_EXPORT_REPORT.md`, extended by
`BABY_FOCUSED_CROP_REPORT.md`) computes a single **static** horizontal crop offset per clip and
holds it for the clip's full duration — deliberately, to avoid the jitter/whiplash of continuous
panning across fast 0.8-2.5s beat-synced cuts (see `VERTICAL_EXPORT_REPORT.md`'s "Crop Offset
Strategy" section for the original reasoning — that reasoning still holds, don't revisit it).

Tomasz watched the fixed vertical renders and asked if the cropping could be smoother. Confirmed
what he wants (asked directly): **not** a return to continuous dynamic panning — a **subtle ease-in
at the start of each clip**, where the crop starts slightly wider/more-neutral and eases into its
final computed position over roughly 0.3-0.5s, then holds static for the rest of the clip. This
should make each cut's framing feel like it settles into place rather than snapping to a fixed crop
instantly, without reintroducing the panning/jitter problem the static-per-clip design avoided.

## What to build

1. In the vertical crop filter construction (`build_crop_to_fill_filter()` /
   wherever the crop `x` offset is emitted into the ffmpeg filtergraph, in `src/ffmpeg_processing.py`
   — read the current implementation first, this spec doesn't dictate the exact function signature),
   change the static `crop_x` value into a **time-varying expression** for the first ~0.3-0.5s of
   each clip, then constant at the final computed offset for the remainder:
   - Starting position: ease from a **more neutral/centered offset** (e.g. the frame's geometric
     center, or partway between center and the final offset — your call, explain the choice) toward
     the final subject-aware offset computed by the existing baby-priority/head-containment logic.
   - Use an **eased curve, not linear** — a standard smoothstep (`3t² - 2t³` on the normalized
     `[0,1]` progress) or equivalent reads far more natural than a linear pan. FFmpeg's `crop`
     filter's `x` parameter accepts a per-frame expression using `t` (seconds since the crop
     filter's own start, i.e. per-clip if applied per-extracted-clip, which this pipeline already
     does per clip) — implement the smoothstep math directly in that expression string.
   - **Clamp the ease duration for short clips**: if a clip's own duration is shorter than roughly
     2x the intended ease duration, scale the ease down proportionally (e.g. cap to
     `min(0.4, clip_duration * 0.4)`) so a rapid-cut clip never spends its entire runtime mid-ease —
     it should always reach and hold its final framing well before the clip ends.
   - Only apply this to clips that actually have a computed subject-aware crop offset different
     from the neutral starting point — a clip whose final offset already IS center (e.g. `Center
     crop` mode, or a clip with no detected subject) doesn't need an ease at all, just render it
     static as today (no pointless motion on an already-centered crop).
2. This only affects vertical-mode rendering — landscape output is untouched (no crop involved
   there at all).
3. Keep this simple and contained to the crop-offset math — don't touch the beat-matched
   transition/crossfade system, the title card, watermark, or ident-outro logic; none of those
   need to change for this.

## Verification (real hardware — required)

On `um890` (same setup as every prior task this session: venv python, app root, `D:\Photos\GoPro\
2025-10-01 Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey +
quality-filter + `min_subject_confidence=0.3`, transitions + title card enabled, vertical
orientation, default `Auto — prefer smaller subject` crop focus):

1. Render and extract a short burst of consecutive frames (e.g. every 0.1s for the first 0.6s) from
   2-3 different clips to confirm the crop position genuinely eases smoothly from the starting
   offset to the final offset, rather than jumping in one step or staying static throughout.
2. Confirm a clip whose final crop is already center (no meaningful subject offset) does NOT show
   any unnecessary ease motion.
3. Confirm short clips (check the actual plan for any clip under ~1s duration) don't have the ease
   eating an awkward fraction of their runtime — verify the clamping logic against a real short clip
   from this footage if one exists in the render.
4. Confirm frame-accurate audio sync and genuine AMF hardware encode are unaffected (same checks as
   every prior verification this session).
5. Confirm landscape mode is completely unaffected (regression spot-check).

## Constraints

- Primarily touch `src/ffmpeg_processing.py` (and `src/video_processor.py` only if the crop offset
  needs to be threaded through differently to support a start/end pair instead of one static value).
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `VERTICAL_CROP_EASE_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output — run AFTER pushing, not before — into the report as proof.**
