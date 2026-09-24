# URGENT REGRESSION: blur/grade from title card leaks across the entire video

## Severity: critical — every render with `title_card_enabled=True` is currently unusable

Confirmed by extracting thumbnails at t=10s, 30s, 50s from a real 60s render
(`music_video_v6_theme_20260923_210330.mp4`, "Warm & Sentimental" theme) — **the entire video is
heavily blurred with the amber color grade applied throughout**, not just the intended ~3s opening
title window. This should only ever affect the opening title card sequence; regular footage
playback must be completely untouched.

## Root cause (found, not guessed — verify this before changing anything else)

In `add_text_overlays_ffmpeg()` in `src/ffmpeg_processing.py` (~line 616), the recombine step is:

```
[themed_bg][orig]blend=all_expr='{blend_expr}':enable='lte(t,{window:.3f})'[resolved]
```

`themed_bg` (the blurred + color-graded + graphic-overlaid stream, itself derived from a full-length
blur of the *entire* video via `[0:v]split=2[orig][blur_in]` → `[blur_in]{blur_chain}[blurred]` with
no trim applied) is passed as the **first** input to `blend`, `orig` as the second.

FFmpeg's timeline `enable` option, on a multi-input filter like `blend`, passes through the **first
declared input unchanged** when the enable condition evaluates false. Here that means: for
`t > window` (i.e. after the title card should have ended), the filter bypasses and the output
becomes `themed_bg` — the blurred/graded stream — instead of `orig`. The inputs are backwards. This
is why the *entire* rendered video, not just the opening ~3s, ends up blurred and amber-tinted.

## Fix

Swap the blend input order so `orig` is first (passed through when disabled) and `themed_bg` is
second:

```
[orig][themed_bg]blend=all_expr='{blend_expr_with_swapped_AB}':enable='lte(t,{window:.3f})'[resolved]
```

**Careful**: `blend_expr` itself references `A` and `B` (built a few lines above as
`if(lte(T,{t_hold}),A, if(gte(T,{window}),B, A*(1-...)+B*(...)))`) where `A` currently means the
*first* blend input and `B` the second. If you swap the input order, you must also either (a) swap
what `A`/`B` mean semantically inside `blend_expr` (i.e. flip which one is "blurred start" vs
"sharp end" in the expression), or (b) keep the expression's A/B semantics and just verify they now
correctly resolve blurred→sharp across `[0, window]` while correctly falling back to the *sharp*
`orig` stream once `enable` goes false. Whichever you do, the two must agree — trace through both
the `t <= window` blended path AND the `t > window` bypass path explicitly and confirm the video is
sharp/normal for the whole tail of the render, not just that the blend math is right at `t=window`.

Also double check the two other title-card branches in the same function that build the same
`[themed_bg][orig]blend=...enable=...[resolved]` pattern (there are two near-identical `fc_parts`
blocks — one with `graphic_src`/`graphic_blend`, one without — both have this same input-order bug,
fix both).

## Why this wasn't caught before

The verification in `AI_TITLE_THEME_REPORT.md`/`TRANSITIONS_AND_TITLE_REPORT.md` only sampled
thumbnails from *within* the title window (0.5s-3.5s) and *at* crossfade boundaries — never a
plain mid-timeline timestamp with no special treatment nearby (e.g. t=10s, t=30s). **For this fix's
verification, always include at least 2-3 thumbnails from timestamps that are NOT near the title
card, NOT near any crossfade boundary** — plain ordinary playback — specifically to catch exactly
this class of "effect leaked further than intended" bug. This should become standard practice for
any future filtergraph change in this repo, not just this one fix.

## Verification (real hardware — required)

On `um890` (same setup as prior tasks: venv python, app root, `D:\Photos\GoPro\2025-10-01
Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey + quality-filter
+ `min_subject_confidence=0.3`, transitions + title card enabled, `start_text="Teresa S.
Dunn\n1st October 2025"`):

1. Re-render and extract thumbnails at t=1s (should be blurred/graded, inside the title window —
   confirm the title card treatment itself still works correctly), t=3.5s (should be fully sharp,
   just past the resolve), and **at minimum t=10s, t=25s, t=45s, t=55s** (all must be completely
   sharp, normal-looking footage with no blur or color grade artifact).
2. Confirm frame-accurate audio sync is still exactly preserved (same ffprobe frame-count/duration
   check used in every prior verification this session).
3. Confirm genuine AMF hardware encode via ffprobe stream tag.
4. Also spot-check with `title_card_enabled=False` (transitions still on) to confirm that path was
   never affected by this bug (it uses the separate "Standard overlay branch" in the same function,
   should be unaffected, but confirm rather than assume).

## Constraints

- Fix only the specific bug described above — do not refactor unrelated parts of the title/theme
  system while you're in there.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `URGENT_BLUR_LEAK_REPORT.md` in the repo root.
- **Commit and push to `origin/main` when done and verified — actually run `git status` and
  `git log origin/main..HEAD` yourself and paste the output into your report as proof, not just a
  checkbox claiming it's done.**
