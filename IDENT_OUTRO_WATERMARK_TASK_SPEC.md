# Task: Ident/outro clip append + watermark option

## Context

Tomasz has a personal-brand "ident" clip (UK broadcast term for a short branding/identity clip) —
a 3D animated logo reveal, `TDD Intro 3D 1.mov`. Already downloaded to a persistent asset location
on `um890`: `D:\BeatSync-Assets\TDD_Intro_3D_1.mov`. Confirmed via ffprobe: 1920x1080, ~29.97fps
(`30000/1001`), 6.006s duration, video codec `qtrle` (QuickTime Animation, near-lossless — this is
why the file is ~1.1GB for 6 seconds), audio codec `pcm_s16le` (uncompressed PCM). **This will need
transcoding/scaling to match whatever the final render's resolution and encoder are** — it cannot
just be concatenated as-is (wrong codec, and its 1920x1080 resolution won't match a 4K landscape or
1080x1920 vertical render without scaling first).

He wants two independent, separately toggleable options in the GUI:

## Option 1: Ident outro — append the clip to the end

Add a GUI checkbox (Create tab, `src/gui.py`, follow the existing pattern for
`transitions_enabled`/`title_card_enabled`): **"Add Ident Outro"**. When enabled, the ident clip
plays in full immediately after the main beat-synced portion ends — this is additional runtime,
not something that eats into the existing beat-synced duration (unlike the title card, which plays
*during* the first clip's own screen time). The ident clip's own audio (it has a PCM audio track)
should play during the outro, not be muted — the main track's audio should have already ended by
then (confirm the main audio doesn't extend into or overlap the outro).

**Technical requirements**:
- Scale/pad the ident clip to match the final render's target resolution (4K landscape 3840x2160
  by default, or 1080x1920 if the vertical export mode from `VERTICAL_EXPORT_TASK_SPEC.md`/
  `VERTICAL_EXPORT_REPORT.md` is also active — check whether that task has landed yet and reuse its
  `target_resolution` plumbing; if not yet landed, just handle the existing landscape target
  resolution and leave a clear note for wiring vertical support in later). Use the existing
  `build_fit_scale_filter()` in `src/ffmpeg_processing.py` (letterbox, don't stretch/distort the
  logo animation — it's a deliberate resolution/aspect mismatch, letterboxing is correct here,
  unlike the vertical-export crop-to-fill case).
- Re-encode to match the main render's codec/framerate (30fps, H264 AMF hardware encoder — same
  settings the rest of the pipeline already uses) before concatenation.
- Concatenate after the main render's last frame (and after any `fade_out` if one is configured —
  check the existing fade_out logic in `add_text_overlays_ffmpeg()`/`create_music_video()` and
  decide whether fade_out should apply to the very end of the ident clip instead, or stay where it
  is on the main content; explain your choice).
- Store the ident clip path as a configurable setting rather than hardcoding
  `D:\BeatSync-Assets\TDD_Intro_3D_1.mov` directly everywhere — a single constant/config point is
  fine (this is a personal-use app, doesn't need a full asset-management UI), but don't scatter the
  literal path across multiple files.

## Option 2: Watermark — small persistent logo overlay

Add a second GUI checkbox: **"Add Watermark"**. This is a *different* treatment from the outro —
a small, semi-transparent static logo shown continuously in a corner of the frame for the entire
main render (not the outro clip's own runtime, which already shows the full ident at full size).

- Extract a single representative frame from the ident clip as the watermark source (pick a frame
  from near the end of its 6s animation, where the logo is presumably fully "resolved"/static
  rather than mid-animation — inspect a few candidate frames and choose the best one, explain your
  choice in the report) — don't try to loop the whole 6s animation as a tiny corner watermark, a
  static logo mark reads better at watermark scale and is far cheaper to composite continuously.
- Composite it small (e.g. ~8-10% of frame width, explain your choice) in a corner (bottom-right is
  the conventional watermark position, but check if there's an existing position-choice pattern in
  this codebase like `_TEXT_POSITIONS` for text overlays and reuse that convention if sensible) at
  moderate opacity (e.g. 50-70% — legible as a mark, not intrusive) for the entire main render
  duration. Use `overlay` composited onto the main video stream — **be careful with input
  ordering exactly like the two bugs already documented in this repo
  (`URGENT_BLUR_LEAK_REPORT.md`, and the correct pattern in
  `TITLE_CARD_DECORATIVE_GRAPHICS_REPORT.md`)** — the main video must be Input 0, the watermark
  PNG Input 1, so nothing breaks if `enable`/timeline gating is used anywhere in this path.
- The watermark option is independent of the outro option — Tomasz should be able to enable either,
  both, or neither.

## Verification (real hardware — required)

On `um890` (same setup as every prior task this session): render with (a) outro only, (b) watermark
only, (c) both together, (d) neither (regression check — must exactly match current behavior).

1. For the outro render: confirm total duration = main render duration + ident clip duration (via
   ffprobe), confirm the ident clip's own audio plays during the outro portion, extract a thumbnail
   from partway through the outro to confirm it displays correctly (letterboxed, not stretched/
   distorted).
2. For the watermark render: extract thumbnails from at least 3 different points across the main
   timeline confirming the watermark is present, correctly positioned, and at reasonable opacity —
   also confirm it does NOT appear during the outro clip itself if outro is also enabled (the
   watermark should apply only to your own beat-synced edit, not duplicate onto the ident clip
   which already displays the full logo).
3. Confirm frame-accurate audio sync for the *main* portion is unaffected by either option (the
   beat-synced section's own duration/frame count should be identical with these options on or
   off — only the ident-outro adds extra runtime, and only at the very end).
4. Confirm genuine AMF hardware encode via ffprobe stream tag on the final concatenated output.

## Constraints

- Touch `src/gui.py`, `src/video_processor.py`, `src/ffmpeg_processing.py` as needed.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir. The ident asset at
  `D:\BeatSync-Assets\TDD_Intro_3D_1.mov` is durable, not disposable — never delete or move it.
- Write findings to `IDENT_OUTRO_WATERMARK_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output — run AFTER pushing, not before — into the report as proof.**
