# Task: Beat-matched transitions/wipes + a blur-to-sharp title card, exposed in the GUI

## Current state (confirmed by grep before writing this spec)

- **Zero transition support exists.** `concatenate_videos_ffmpeg()` in `src/ffmpeg_processing.py`
  (~line 746) does plain hard cuts between every clip. No `xfade`, no wipe, no crossfade anywhere
  in the codebase.
- **A per-beat "impact" score already exists** and is exactly the right signal to drive
  beat-matched transition choice: `impact_score` is computed per beat in
  `src/auto_mode/stage2_features.py` (~line 52, `_normalize(0.42*rhythm_score + 0.24*novelty +
  0.24*wave + 0.10*arc)`), and `src/auto_mode/__init__.py` (~line 304) already derives a
  "strong impact" threshold via `_safe_percentile(impact, 88, 0.88)` (the 88th percentile) for a
  different purpose (cut-density decisions) — reuse the same kind of percentile-based "is this a
  strong beat" test rather than inventing a new one.
- **`start_text`/`fade_in_seconds` already exist** (`create_music_video()` in
  `src/video_processor.py`, ~line 867-932) as a plain text overlay burned onto the first clip plus
  a separate black fade-in — this is NOT what's being asked for below (a separate blur-to-sharp
  title treatment, not a black fade with text on top), but it establishes the parameter-plumbing
  pattern (GUI control → `gui.process_video()` → `create_music_video()` → the ffmpeg assembly
  layer) to follow for the new options.
- GUI (`src/gui.py`, `create_ui()`, ~line 1386-1477) already has `gr.Checkbox` (`strict_mode`,
  `fade_enabled`) and `gr.Textbox` (`start_text`) controls in the Create tab — follow this existing
  pattern for the new controls, don't invent a different UI paradigm.

## Feature 1: Beat-matched transitions

- At each cut point between two consecutive clips in the final timeline, decide the transition
  based on the *incoming* beat's impact score (or whichever of the two adjacent beats is the more
  natural "this is the moment" signal — read `stage6_av_planner.py`'s beat/cut assignment to see
  which beat index maps to which cut boundary before deciding):
  - **Strong beat** (top ~12% by impact, matching the existing 88th-percentile convention above):
    keep a **hard cut** — the punch of a hard cut on a strong beat is the desired effect, not
    something to soften.
  - **Weaker beat**: apply a short **crossfade/dissolve** (ffmpeg `xfade` filter, transition type
    `fade`) instead of a hard cut.
- Use a short, fixed crossfade duration (recommend 0.25-0.4s — pick one value, don't make this
  itself a slider unless trivial; explain your choice in the report).
- **Critical constraint — do not break frame-accurate audio sync.** This app's `create_music_video()`
  docstring explicitly says "PURE FFMPEG IMPLEMENTATION - FRAME-ACCURATE" and the whole pipeline
  keeps final video duration exactly matched to the audio track (confirmed across every render
  this session: `Audio duration: NN.NNs` always equals the rendered output's duration to the
  frame). A crossfade needs the two adjacent clips to *overlap* in time by the crossfade duration,
  which — if not compensated for — will shift every subsequent cut later and desync from the beat
  grid. You MUST compensate for this (e.g. shorten each clip's extracted duration by the
  overlap amount split across its two edges, or absorb the overlap into the edge-buffer math
  `edge_buffer_seconds` already uses) so the final assembled timeline still lands on the exact
  same beat grid and total duration as it would with hard cuts. Explain exactly how you preserved
  this invariant in your report, and verify it explicitly (see Verification below) — this is the
  single most important thing not to get wrong.
- No transition should ever be applied at the very first or very last clip boundary (there's
  nothing to cross-fade into/from at the timeline edges — those are handled by the separate title
  card / fade_out below, not this feature).

## Feature 2: Blur-to-sharp title card

Replace/extend the current `start_text` treatment with an opening sequence that visually *merges*
into the first real clip rather than being a separate title screen or a plain text-over-video
overlay:

- Take the first ~2-3 seconds of frames from the actual first selected clip (the same clip that
  would normally play first).
- For roughly the first half of that window: heavily blurred (e.g. ffmpeg `gblur`) and dimmed,
  with the title text (reuse the existing `start_text` input — don't rename/replace that param,
  just change how it's rendered) overlaid, clearly readable against the blurred backdrop.
- Smoothly interpolate blur amount and brightness back to normal over the remainder of the window,
  so by the end the viewer is watching the sharp, normally-exposed first clip with the text having
  faded away — i.e. the title visually *resolves into* the footage rather than cutting away from
  a title card to the video. (ffmpeg can animate a blur-strength/brightness parameter over time
  via `sendcmd`/`zmq` or by pre-rendering a handful of blur-strength keyframes and cross-dissolving
  between them — pick whichever approach fits this app's existing
  frame-accurate/pure-ffmpeg architecture; explain your choice.)
- This should be an **additive** option, not force-on: gate it behind a new checkbox (see GUI
  section below) so a render without a title still works exactly as today when the checkbox is off
  and/or `start_text` is empty.
- Total output duration should still exactly match the audio track — the title sequence plays
  *during* the first clip's normal screen time, it isn't extra runtime tacked onto the front,
  unless there is a genuinely good reason to add a small fixed extension (state your choice and
  reasoning explicitly in the report if you go that route).

## GUI wiring (Tomasz explicitly asked for this — do not skip)

Add real controls to the Create tab in `src/gui.py`'s `create_ui()`, following the existing
`gr.Checkbox`/`gr.Textbox` patterns already there (`strict_mode`, `fade_enabled`, `start_text`):

- A checkbox to enable/disable beat-matched transitions (default on, since it's the requested
  behavior — but make it toggleable).
- A checkbox to enable/disable the blur-to-sharp title treatment (default off unless `start_text`
  is non-empty — use your judgement on the exact default UX, explain it in the report).
- Wire both through `process_video()` → `create_music_video()` the same way `fade_enabled`/
  `start_text` already are (see the existing param-threading pattern at
  `src/video_processor.py` ~line 1209-1313 and 1433-1641 in `src/gui.py` — these list every wired
  parameter name, follow the same trail for the two new ones).

## Verification (real hardware — required, do not skip)

On `um890` (venv python: `C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe`, app
root `C:\BeatSyncTest\app\BeatSync-Engine-main`, test footage
`D:\Photos\GoPro\2025-10-01 Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm
analysis cache, journey mode + quality filter + `min_subject_confidence=0.3` are this repo's
current validated-good baseline settings — use them):

1. Render once with transitions + title card **enabled**, once with both **disabled** (should
   reproduce the exact prior `music_video_v4_journey_20260923_134417.mp4`-equivalent output/plan
   for a straightforward regression check).
2. **Confirm exact audio-sync preservation**: `ffprobe` the enabled-transitions output and confirm
   its total duration still matches the audio track duration to the frame, the same way every
   prior render this session has (`Audio duration: NN.NNs` == output duration). This is the
   specific thing most likely to silently break — check it explicitly, don't assume it.
3. Extract thumbnails at a couple of transition points to visually confirm hard cuts land on
   strong beats and crossfades appear on weaker ones (cross-reference against the beat/impact data
   in the plan JSON, same technique used earlier this session for the black-frame/blur bugs).
4. Extract thumbnails from the opening ~3s of the title-card render to visually confirm the
   blur-to-sharp resolve actually happens (not just a hard cut from a blurred frame to a sharp
   one).
5. Confirm genuine AMF hardware encode via `ffprobe` stream tag (`Lavc... h264_amf`), same check
   used in every prior verification this session.

## Constraints

- Primarily touch `src/ffmpeg_processing.py`, `src/video_processor.py`, `src/gui.py`, and
  `src/auto_mode/stage6_av_planner.py` as relevant.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `TRANSITIONS_AND_TITLE_REPORT.md` in the repo root (same tone/detail as
  `JOURNEY_SOURCE_COVERAGE_REPORT.md`/`QUALITY_FILTER_REPORT.md` in this repo).
- **Commit and push to `origin/main` when done and verified — and actually run `git log`/`git
  status` to confirm the push landed before calling the task done.** (A prior task this session
  claimed "committed and pushed" in its report when it hadn't actually committed anything — verify
  this yourself rather than just writing the words in the report.)
