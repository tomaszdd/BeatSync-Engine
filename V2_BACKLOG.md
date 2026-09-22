# Backlog — later scope, not part of the current subject-detection/max-clip-length build

Ideas captured from real usage/review, deliberately not fleshed out to full
TASK_SPEC.md depth yet — expand into a proper spec (see `SUBJECT_DETECTION_TASK_SPEC.md`
for the expected format/rigor) when one of these is actually picked up.

## 1. Automated per-cut transitions/swipes synced to the beat (GoPro Quik-style)
Checked: the only cut-styling that exists today is a single start/end fade
(`fade_enabled`/`fade_duration` in `gui.py`). Every cut between clips is a hard cut —
no per-cut transition variety at all.

Scope: use ffmpeg's `xfade` filter (crossfade, wipe left/right/up/down, slide,
zoom-punch, flash/white, pixelize, circle-open, etc.) and pick the transition per cut
based on beat intensity/type already available from the beat-detection pass — a strong
downbeat gets a punchier transition, a soft beat stays a simple cut or gentle crossfade.
New GUI setting, e.g. "Auto transitions" on/off + intensity.

## 2. Render the same edit at multiple resolutions without re-running analysis
Checked: `target_resolution` already exists as a per-render setting with portrait/
landscape scale-crop logic in `ffmpeg_processing.py` — single-resolution export already
works, including portrait. What's missing is *re-exporting an already-made edit* at a
different resolution cheaply.

Good news: this is cheaper than it sounds. `clip_plan.py` already has
`build_render_plan()`/`save_render_plan()`/`load_render_plan()` — every render already
persists a reusable `.plan.json` (confirmed, e.g. `output/music_video_20260922_171820.plan.json`).
The expensive part (beat detection, candidate scoring/AI analysis, clip selection) is
already decoupled from final encode. Scope: a GUI action "export this plan at another
resolution" that loads an existing plan and re-runs just the ffmpeg assembly stage with
a different `target_resolution`, skipping analysis entirely. Multi-resolution batch
export (tick several resolutions, get several files from one render pass) falls out of
this almost for free once single re-export works.

## 3. Auto-upload to YouTube (and possibly other platforms)
Doesn't exist at all currently — no upload/OAuth code anywhere in the repo. Real net-new
infrastructure, not a small add-on:
- **YouTube**: feasible — YouTube Data API v3, needs a Google Cloud project + OAuth
  consent screen + stored refresh token. Default the upload visibility to
  **unlisted or private**, never public, given this renders personal/family footage —
  that's a deliberate default to set, not an afterthought.
- **Instagram/TikTok**: significantly harder. Both gate programmatic upload behind
  business/creator-account API partnerships (Instagram Graph API requires a Business or
  Creator account plus app review; TikTok's Content Posting API is also partner-gated).
  Don't assume feasibility parity with YouTube — investigate access requirements before
  committing to scope, and it may not be realistically buildable as a personal project.
  There are unofficial libraries (e.g. `instagrapi`, a private-API wrapper) that bypass
  the official Graph API restrictions — **project owner flagged real risk here**:
  automating via a reverse-engineered private API violates Instagram's ToS and is a known
  way to get an account soft-banned/action-blocked (temporary posting/engagement
  restrictions) or worse. Don't build against an unofficial API for a real personal
  account without accepting that risk explicitly — if this is ever picked up, default to
  the official Graph API route despite the extra approval friction, not `instagrapi` or
  similar.

## 4. AI vertical reframe ("Instagram cut") — the "proper AI task"
Take a landscape/wide source edit and produce a 9:16 vertical crop that pans/tracks to
keep the subject in frame, rather than a dumb centre-crop that clips people out of shot.
This is a real computer-vision task (similar to what Opus Clip/Descript's auto-reframe
does), and it has a natural synergy with `SUBJECT_DETECTION_TASK_SPEC.md`'s Layer 1: that
spec already adds YOLOv8n person-detection producing bounding boxes per candidate window
to flag "no subject visible" — those same bounding boxes are exactly the signal needed to
drive a smart-crop window's x-position per frame/shot. Build this *after* Layer 1 lands
rather than as fully separate work — reuse its detections rather than running a second
person-detector pass.

Needs its own design pass on the harder part: smoothing the crop-window movement so it
pans rather than jitters frame-to-frame (e.g. a damped/low-pass filter on the tracked
x-position, not a raw per-frame follow), and a fallback for shots with multiple/no
detected people (centre-crop, or hold last known position).
