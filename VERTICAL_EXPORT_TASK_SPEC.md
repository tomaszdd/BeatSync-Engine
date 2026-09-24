# Task: Vertical (9:16) export mode for Instagram/phone viewing

## Context

Tomasz wants a vertical export option for Instagram Reels/Stories. Confirmed by reading the code
before writing this spec: there is currently **no** aspect-ratio/orientation option anywhere —
`target_resolution` is always just inherited from the source footage's native resolution
(`get_video_resolution(video_files[0])` in `video_processor.py`/`gui.py`), and the existing
`build_fit_scale_filter()` (`ffmpeg_processing.py` ~line 274) letterboxes any mismatched aspect
ratio with black pad bars rather than cropping to fill — fine for a stray portrait photo dropped
into an otherwise-landscape edit, wrong for a deliberate full-frame vertical export (nobody wants
their Instagram Reel to be a small landscape strip with black bars top and bottom).

## What to build

### 1. GUI orientation control

Add a control to the Create tab (`src/gui.py`, follow the existing `gr.Radio` pattern used for
`clip_order_mode`/`title_theme`): **"Export Orientation"** with options `Landscape (16:9)`
(default, current behavior unchanged) and `Vertical (9:16 — Instagram/Reels)`. When vertical is
selected, force `target_resolution = (1080, 1920)` regardless of source footage resolution (this
is a deliberate fixed target — Instagram expects that exact pixel size, don't derive it from
source aspect ratio). Wire through the same parameter-threading trail as `title_theme`/
`transitions_enabled` (settings persistence, `process_video()`, `create_music_video()`,
`refine_rerender()`).

### 2. Smart crop-to-fill (not letterbox) for vertical mode

When exporting vertical from landscape 16:9 GoPro source footage, a plain center-crop or (worse)
letterbox produces a bad result. This pipeline already computes **YOLO subject bounding boxes**
per candidate frame as part of the quality/subject-detection filtering work
(`SUBJECT_DETECTION_REPORT.md`, `src/subject_detection.py` — check exactly what bbox data is
already available and retained per candidate before adding new detection work; reuse what's
already computed rather than re-running YOLO if the data's already there).

For vertical mode specifically, implement a **horizontal crop-to-fill** that's centered on the
detected subject's bounding box when available (rather than the frame's geometric center), falling
back to a plain center-crop when no subject bbox exists for that candidate (e.g. a genuinely
subject-less establishing shot, or if subject-detection data isn't available for that clip for any
reason). Concretely: scale the source so its height matches 1920px, then crop a 1080px-wide window
from the resulting frame, horizontally positioned to keep the subject's bbox center as close to the
crop window's center as the source frame's edges allow (clamp so the crop window never goes outside
the source frame).

This does not need to be a per-frame dynamically panning virtual camera (that's a much bigger,
separate feature — don't build it here) — a single crop offset computed per clip (from the
subject's average/first-detected bbox position within that clip) is sufficient and much simpler.
State clearly in your report if you chose per-clip-static vs any dynamic panning, and why.

### 3. Everything else must adapt correctly to the new 1080x1920 canvas

Confirm (don't assume) that these already-built systems correctly scale to the vertical canvas
rather than being landscape-resolution-assumption bugs:
- Title card typography sizing/positioning (`_compute_text_layout()` in `src/title_theme.py` — it
  already scales proportionally to `width`/`height`, verify this actually produces a legible,
  well-composed result in portrait, not just that it doesn't crash).
- Decorative motifs (`TITLE_CARD_DECORATIVE_GRAPHICS_REPORT.md` — corner brackets / confetti /
  chevrons — verify they look correct and don't overflow or look sparse/misplaced in a much
  taller, narrower frame).
- Procedural title-card background textures (bokeh/particles/streaks — these already reference
  `frame_w`/`frame_h` dynamically, confirm this holds for 1080x1920 too).
- Beat-matched transition crossfades and their theme tints (should be resolution-independent
  already, but confirm no hardcoded landscape assumption snuck in).

## Verification (real hardware — required)

On `um890` (same setup as every prior task this session: venv python, app root, `D:\Photos\GoPro\
2025-10-01 Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey +
quality-filter + `min_subject_confidence=0.3`, transitions + title card enabled, `start_text=
"Teresa S. Dunn\n1st October 2025"`):

1. Render once in the new Vertical mode. Confirm output resolution is exactly 1080x1920 via
   ffprobe.
2. Extract thumbnails from at least 4-5 different clips across the timeline and visually confirm
   the subject (person/baby) is reasonably framed — not cut off at the crop edges, not
   dramatically off-center — compare a couple against the same clips' framing in the existing
   landscape output to sanity-check the crop logic actually used subject-position data, not just a
   blind center-crop.
3. Extract thumbnails from the title card window and confirm typography + decorative motif render
   correctly and legibly in the portrait frame.
4. Confirm frame-accurate audio sync is still exactly preserved (ffprobe frame count/duration
   check, same as every prior verification this session).
5. Confirm genuine AMF hardware encode via ffprobe stream tag.
6. Confirm Landscape mode (the default) is completely unaffected — render or spot-check to confirm
   no regression to the existing behavior.

## Constraints

- Touch `src/gui.py`, `src/video_processor.py`, `src/ffmpeg_processing.py`, and
  `src/subject_detection.py`/`src/auto_mode/stage6_av_planner.py` as needed to thread subject bbox
  data through to the crop-positioning logic.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `VERTICAL_EXPORT_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output — run AFTER pushing, not before — into the report as proof.** Two of the last two tasks
  in this repo got this right; keep that streak going.
