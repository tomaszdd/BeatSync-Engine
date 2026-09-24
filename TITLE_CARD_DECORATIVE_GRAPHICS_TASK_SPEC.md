# Task: Designed decorative graphics around the title card text

## Context

The title card system (`AI_TITLE_THEME_REPORT.md`, `src/title_theme.py`,
`add_text_overlays_ffmpeg()` in `src/ffmpeg_processing.py`) currently gives each theme a
*procedural texture* behind the text — `bokeh_light_leak`/`light_particles`/`light_streaks`, all
built from `noise`+`gblur`+`eq` (abstract blurred noise, no actual shapes or motifs). Tomasz wants
something more explicitly **designed**: real decorative graphic elements positioned around the
title text itself — border/frame accents, corner flourishes, small ornamental motifs — not just
background texture.

**Explicit scope decision from Tomasz** (asked directly): these should be **coded/drawn decorative
elements** (vector shapes via PIL/Pillow or ffmpeg drawing primitives), not AI-generated
illustrated artwork from an external image model. Stay local, fast, no new API dependency — this
extends the existing procedural-graphics approach, doesn't replace it with something needing a
network call. Since Tomasz asked specifically for "the AI antigravity" to do this, this should be
delegated to `antigravity_cli`, continuing the pattern already used for the rest of the title/theme
work in this repo.

## What to design (one motif per existing theme, matching its established aesthetic)

Each theme already has a font pairing, color grade, and accent color (`src/title_theme.py`'s
`THEME_PRESETS`) — reuse the existing accent color for the new decorative elements so they're
visually consistent with what's already there, don't invent new colors.

1. **Warm & Sentimental**: delicate thin corner-frame accents (fine double or single hairlines
   forming subtle corner brackets around the text block) in the theme's champagne-gold accent
   color, plus a small, minimal motif (e.g. a simple line-drawn leaf or heart, restrained, not
   cartoonish) placed near the subtitle line. Elegant, sparse — matches Playfair Display's formal
   serif character.
2. **Joyful & Bright**: a scatter of small soft-edged circles/dots (like gentle confetti) around
   the text block, varying size, in the theme's pastel peach accent color plus a couple of
   complementary soft tones. Playful, light — matches Quicksand's rounded friendliness.
3. **Upbeat & Energetic**: a few bold angular accent lines/chevrons flanking the text (like a
   sports/action-graphics accent), in white/high-contrast, dynamic diagonal placement. Punchy —
   matches Bebas Neue's bold condensed character.

Keep every motif genuinely restrained — this decorates the title card, it must not compete with or
obscure the text, and it must never visually resemble the procedural background texture already
there (this should read as an additional, distinct layer of intentional design, not more noise).

## Implementation approach

Render each theme's decorative motif once as a transparent PNG (via PIL/Pillow — already likely
available, check `requirements.txt`/existing imports before adding a new dependency; if not
present, a lightweight pure-Python vector drawing approach is fine, avoid heavy new dependencies)
at the render's actual output resolution (or scalable), then composite it into the title-card
filtergraph via ffmpeg `overlay` during the same title window as the existing blur-to-sharp
sequence — same timing (`t_hold`/`window` from the existing title-card code), so the decorative
graphic appears and fades with the rest of the title treatment, not as a separate step.

## ⚠️ Critical — do not repeat the exact bug just fixed in this repo

`URGENT_BLUR_LEAK_REPORT.md` documents a severe regression from the *previous* title-card task:
a `blend` filter's `enable='lte(t,window)'` bypass passed through the WRONG input (first-declared)
once the enable condition went false, causing an effect meant only for the opening ~3s to leak
across the entire video. **`overlay` has similar timeline-`enable` bypass semantics** — when
disabled, it passes through its main (first) input unchanged. Get the input order right: the plain
video/title-card composite must be the *first* input to `overlay`, the decorative graphic PNG the
*second*, so that once `enable` goes false (title window ends), the output correctly reverts to
the video without the decorative graphic — not the other way around. **Explicitly verify this with
thumbnails from plain mid-timeline timestamps (t=10s, t=30s, t=50s or similar) showing zero trace
of the decorative graphic**, exactly the check that was missing from the original title-theme
task and caused the last bug.

## Verification (real hardware — required)

On `um890` (same setup as every prior task this session: venv python, app root, `D:\Photos\GoPro\
2025-10-01 Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey +
quality-filter + `min_subject_confidence=0.3`, transitions + title card enabled, `start_text=
"Teresa S. Dunn\n1st October 2025"`):

1. Render with `title_theme=Auto` (should select "Warm & Sentimental" for this footage, as
   established in the prior task) and extract thumbnails within the title window (e.g. t=0.5s,
   1.5s, 2.5s) confirming the new decorative motif renders correctly alongside the existing
   typography and procedural texture.
2. **Extract thumbnails from at least 3 plain mid-timeline timestamps (well outside the title
   window and away from any transition boundary) and confirm zero trace of the decorative
   graphic** — this is the specific regression class to guard against, per the warning above.
3. Manually force each of the other two themes and confirm their distinct decorative motifs render
   correctly (spot-check, thumbnails only, doesn't need full 60s renders for all three).
4. Confirm frame-accurate audio sync is still exactly preserved (ffprobe frame count/duration
   check, same as every prior verification this session).
5. Confirm genuine AMF hardware encode via ffprobe stream tag.

## Constraints

- Touch `src/title_theme.py` (add motif definitions/rendering) and `src/ffmpeg_processing.py`
  (composite into the title-card filtergraph) as needed.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `TITLE_CARD_DECORATIVE_GRAPHICS_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output into the report as proof — not a template, not a placeholder, the actual command output,
  run after the push, not before.** This exact self-verification step has been incomplete or
  inaccurate in 3 of the last 5 tasks in this repo. Do not let this be a 4th.
