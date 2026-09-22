# Task: add a configurable max clip/segment length

## Problem
Tomasz reported a render where a clip "stretched to the music" — one shot held on screen
for a long time — rather than the music being cut to match the clip.

Investigated the most recent render's plan (`music_video_20260922_171820.plan.json`): in
that specific render every clip's `final_duration` exactly equals its `source_duration`
(zero clips with any mismatch, max clip length only 5.1s) — so no time-stretch happened
there; that track's beats are dense enough that it didn't surface. But confirmed via grep
across `src/*.py` that **no `max_clip_length`/`max_segment_duration` setting exists
anywhere in the app** — nothing currently caps how long a single continuous shot can be
held. On a track with a sparser/slower section (large gaps between detected beats), the
whole inter-beat gap becomes one segment with no upper bound, and one clip fills the
entire gap. Whether this specifically produced the "station" example needs reproducing
on the actual source render Tomasz saw it in — ask him which output/audio track if not
obvious from `output/` folder timestamps.

## Fix
Add a `max_clip_seconds` setting (numeric input in the GUI, default blank/uncapped =
today's behavior, so nothing changes unless the user sets it) plumbed through the same
path as the existing `edge_buffer_seconds`/`clip_order_mode` settings:
- `gui.py` DEFAULT_SETTINGS dict (~line 1199, alongside `'edge_buffer_seconds': 2.0,
  'clip_order_mode': 'auto',`)
- the render call (~line 611, alongside `edge_buffer_seconds=...`, `clip_order_mode=...`)
- session/plan persistence (~lines 1303, 1622, alongside the same two settings)

Where a beat-to-beat gap (or held-shot segment under Journey/Chronological mode when
footage runs out) exceeds `max_clip_seconds`, split it into multiple sub-segments with
synthetic intermediate cut points instead of one long hold or a stretch. Reuse the
existing segment/candidate-window machinery in `video_analysis.py`
(`_build_boundaries()` ~line 851, `_make_candidate_windows()` ~line 865) rather than
building a parallel path — each sub-segment becomes its own independently-scored
candidate/cut, same as today's normal beat-aligned segments.

## Verification
Test against a track with a genuinely sparse section (long gap between two consecutive
detected beats — check `beat_times` in a rendered `.plan.json` for the biggest gap, or
pick/construct a track with a slow intro) to actually exercise the cap, not just a fast
track like the one already rendered (which never needs it). Confirm in the output
`.plan.json` that no clip exceeds the configured `max_clip_seconds`, and that setting it
to blank/0 reproduces today's uncapped behavior exactly (no regression for existing
renders).

## Report
Write findings to `MAX_CLIP_LENGTH_REPORT.md` in repo root when done.
