# Task: Fix jarring vertical crop cuts — ultra-short clips + ease-always-resets-to-center

## Context

Tomasz flagged the vertical export (already through several rounds of fixes: baby-priority
selection, head/face containment, per-clip ease-in — see `BABY_FOCUSED_CROP_REPORT.md`,
`VERTICAL_CROP_EASE_REPORT.md`) as still having "funny crops and cuts... quite jarring" on a real
render against a new, faster/denser music track (123 BPM "Trap Beauty", vs. the original 129.2 BPM
track used in prior verification — this track's `Drop`/`Chorus` sections cut much faster).

## Two real, confirmed root causes (found by inspecting the actual render's plan.json, not guessed)

Source: `music_video_v11_newmusic_20260924_203020.plan.json` on `um890`
(`D:\Photos\GoPro\2025-10-01 Tereska Birth`, vertical 9:16, journey order, quality filter 0.3,
transitions + title card + ident outro + watermark all on, default `Auto — prefer smaller subject`
crop focus).

### Root cause 1: ultra-short clips get the same ease treatment as normal ones

Several clips in this real render are extremely short: clip index 0 is **0.07 seconds**, index 6 is
**0.47s**, index 9 is **0.47s**. The existing ease-clamp formula (`min(0.4, clip_duration * 0.4)`
from `VERTICAL_CROP_EASE_REPORT.md`) technically produces a tiny ease window for these (e.g. 0.028s
for the 0.07s clip), but a clip this short is essentially a single-frame flash regardless of crop
handling — there's no meaningful "settle into framing" to perceive, and re-running subject detection
on a near-instantaneous clip is itself likely to be noisy/unreliable (one sampled frame from 0.07s
of source footage could easily catch a transient/motion-blurred moment).

**Decide and implement a sensible floor**: below some minimum clip duration (propose ~0.3-0.4s as a
starting point, but look at the real distribution of clip durations across this and prior renders
before picking a hard number, and explain your choice), either (a) skip the ease and per-clip
subject re-detection entirely and just hold whatever crop position the adjacent/previous clip was
using, or (b) some other sensible simplification — your call, but the guiding principle is: a
clip too short to visually register a "settle" shouldn't be paying the cost (and risk) of an
independent subject-detection + ease cycle. State clearly what you chose and why.

### Root cause 2: every clip's ease always starts from frame-center, never from the previous clip's ending position

Confirmed from the real data: cut-to-cut jumps in `cx` (subject bbox center, a proxy for crop
position) are frequently huge — e.g. clip 3→4: `0.065 → 0.376` (jump 0.311), clip 8→9:
`0.279 → 0.663` (jump 0.384), clip 17→18: `0.877 → 0.408` (jump 0.469). These are real, and large
framing changes between genuinely different shots/sources are not inherently wrong — a hard cut on
a strong beat SHOULD look different, that's the point.

The actual design problem is orthogonal to those cut-to-cut jumps: `VERTICAL_CROP_EASE_REPORT.md`'s
implementation always starts each clip's own ease from **frame-center** (`cx_norm = 0.5`), not from
wherever the *previous* clip's crop settled. This means at every single cut — including ones that
land inside a **beat-matched crossfade** (`TRANSITIONS_AND_TITLE_REPORT.md`), where the two clips'
pixels are actually blended together for ~0.35s — the outgoing clip is showing its own settled,
possibly far-off-center framing while the incoming clip's blended pixels start from a
freshly-reset-to-center crop. During the blend window this reads as two very differently-framed
versions of the video ghosting together, which is very plausibly what "funny crops" looks like in
practice, independent of any single clip's own bbox being right or wrong.

**Fix**: at a hard cut, resetting to center-then-easing is fine (no crossfade to look weird during,
a hard cut is a clean instant switch). But for a boundary that has a crossfade
(`compute_beat_transitions()`/`compute_clip_handles()` from `TRANSITIONS_AND_TITLE_REPORT.md`
already know which boundaries are crossfades and their duration — thread that information to the
crop-ease logic if it isn't already available there), the **incoming clip's ease should start from
the outgoing clip's final crop position**, not from frame-center, so the two blending video streams
share a much closer framing during the actual blend window and only diverge (continuing to ease
toward the incoming clip's own true final position) after the crossfade has resolved to the
incoming clip alone. Read how `_build_transition_filtergraph()` currently wires clip boundaries
together before deciding the cleanest way to pass "previous clip's settled crop_x" into the next
clip's crop expression — this may require passing an extra parameter through the same clip-list
structure that already carries `subject_bbox` per clip.

## Verification (real hardware — required)

On `um890` (same footage/settings as this bug report's source render, `trap_beauty_60s.mp3` is
already at `C:\BeatSyncTest\trap_beauty_60s.mp3` if useful for reproducing the exact same clip
selection, though the older `audio_60s.mp3` test track works too since duration distribution issues
aren't music-specific):

1. Re-render vertical mode and confirm via the new plan.json that ultra-short clips (find whichever
   ones land in this build) no longer trigger a full independent ease/re-detection cycle per your
   chosen fix.
2. For at least 2-3 real crossfade boundaries where the two clips' final crop positions are far
   apart, extract frames spanning the crossfade window and visually confirm the incoming clip's
   crop starts near the outgoing clip's ending position rather than snapping to center — compare
   against the pre-fix behavior (re-render with the fix reverted, or just reason from the known-old
   formula, whichever is faster) to show the before/after difference concretely.
3. Confirm hard-cut boundaries (no crossfade) still work as before — resetting to center-then-
   easing for those is fine, don't change that case unnecessarily.
4. Confirm frame-accurate audio sync and genuine AMF hardware encode are unaffected.
5. Confirm landscape mode is completely unaffected (no crop there at all).
6. Run the full existing test suite, confirm nothing regresses.

## Constraints

- Primarily touch `src/ffmpeg_processing.py` (crop-ease expression construction) and
  `src/video_processor.py`/`src/auto_mode/stage6_av_planner.py` if crossfade-boundary info or
  previous-clip crop_x needs threading through differently.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `CROP_CONTINUITY_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output — run AFTER pushing, not before — into the report as proof.**
