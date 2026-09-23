# Task: Guarantee at least one clip per usable source in journey mode

## Bug, confirmed on real footage

`_build_journey_sequence()` / `_journey_chapter_counts()` in `src/auto_mode/stage6_av_planner.py`
allocate each footage chapter a soft "quota" of output segments proportional to its usable
duration (`budget[v]` in `_journey_chapter_counts`, `usable[v]` from `_source_usable_seconds()`).
When a chapter can't deliver its quota (`_journey_forward_start()` returns `None` before `quota`
is reached — e.g. a short clip has too little usable footage left after `edge_buffer_seconds`
trimming and the quality filter added in `QUALITY_FILTER_REPORT.md`), the shortfall becomes
`deficit = quota - got` and is **added to the next chapter's quota**. This is by design for
smoothing small shortfalls, but in practice it means a source that can deliver *zero* clips is
silently skipped entirely and its whole allocation dumps onto whichever chapter happens to follow
— which may already be a large, well-supplied source, making the imbalance worse, not better.

Confirmed real example (`D:\Photos\GoPro\2025-10-01 Tereska Birth\` on `um890`, `ssh um890`,
`music_video_v4_journey_20260923_132414.plan.json`, 60s render, `min_subject_confidence=0.3`,
quality filter active): `GX013844.MP4` (4.2s), `GX013845.MP4` (7.4s), `GX013846.MP4` (7.6s),
`GX013847.MP4` (7.0s) were each budgeted `x2` chapters per the `Journey chapters (capture time):`
debug log, but **all four got zero actual clips** in the final plan. Their combined deficit (8
segments) rolled forward and landed disproportionately on `GX013848.MP4` (6 clips) and
`GX013849.MP4` (10 clips) — a single long recording ending up with 10 of the render's 33 total
clips while four distinct real moments from the same event don't appear at all.

For a family-memory video, a distinct recorded moment (even a short one) being completely absent
while one long recording dominates the final cut is a worse outcome than giving that short clip
just one brief appearance, even if it slightly changes the render's rhythm/pacing math.

## What to do

1. Read `_journey_chapter_counts()` and `_build_journey_sequence()` in full
   (`src/auto_mode/stage6_av_planner.py`, ~line 599-780) to understand the current quota/deficit
   mechanism precisely before changing it.
2. Change the allocation so that **every footage chapter with `usable[v] >= 0.2` (the existing
   eligibility threshold already in the code) gets first claim to at least 1 delivered clip**
   before any surplus is distributed proportionally to larger sources. Concretely: a source should
   only end up with 0 actual clips if `_journey_forward_start()` genuinely cannot produce even one
   valid candidate for it (e.g. every candidate in that source was quality-filtered out) — not
   merely because its *proportional* quota was small and got swallowed by deficit rollover from an
   earlier chapter.
3. Preserve the existing behavior for everything else: total segment count must still equal `n`
   (the number of profiles/beats), forward-only-never-revisits semantics must be unchanged, and
   sources that genuinely have zero usable candidates (fully quality-filtered, e.g. `GX013854`'s
   mostly-black footage) should still legitimately get 0 clips — don't force a clip out of footage
   that's truly unusable.
4. Think about the tradeoff you're making explicitly and say so in your report: guaranteeing 1 clip
   per usable source means proportional weighting for the *remaining* segments after those
   guaranteed slots needs adjusting (e.g. reduce large sources' surplus quota by the total guaranteed
   floor first, then distribute the rest by the existing weight formula) — don't just bolt on a
   floor without adjusting the remainder math, or total segment count could overshoot/undershoot `n`.

## Verification (real hardware — required)

On `um890` (venv python: `C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe`, app
root `C:\BeatSyncTest\app\BeatSync-Engine-main`, footage `D:\Photos\GoPro\2025-10-01 Tereska Birth\`,
60s trimmed audio at `C:\BeatSyncTest\audio_60s.mp3`, warm analysis cache already in place):

- Re-run the exact same render (`clip_order_mode='journey'`, `min_subject_confidence=0.3`,
  60s audio) and confirm via the resulting `*.plan.json`'s `clips` array that `GX013844`,
  `GX013845`, `GX013846`, `GX013847` (and any other source with `usable >= 0.2` that previously
  got 0 clips) now each appear **at least once**.
- Confirm the total clip count still matches the number of beats/segments planned (no off-by-one
  regressions from the quota math change).
- Confirm `GX013854` (mostly quality-filtered-out footage) still correctly gets 0 or very few
  clips if it genuinely has little/no usable content — don't force padding out of unusable footage
  just to hit a floor.
- Report the before/after per-source clip-count distribution (a simple `Counter` over
  `clips[i]['source_name']` from the plan JSON, same as used to diagnose this bug) so the fix is
  demonstrably verified, not just asserted.

## Constraints

- Primarily touch `src/auto_mode/stage6_av_planner.py`. If the real fix point is elsewhere, fix it
  there and explain why.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `JOURNEY_SOURCE_COVERAGE_REPORT.md` in the repo root (same tone/detail as
  `QUALITY_FILTER_REPORT.md`/`VIDEO_ANALYSIS_CACHE_FIX_REPORT.md` in this repo).
- Commit and push to `origin/main` when done and verified.
