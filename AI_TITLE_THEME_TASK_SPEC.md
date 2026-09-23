# Task: AI mood-matched title typography/graphics + themed transitions

## Context

Tomasz wants the title card to use real designed typography and a matching graphic treatment that
suits the specific video/music (not the plain default `Arial` text currently used via `start_text`
in `src/ui_content.py`'s `_FONTS`/`DEFAULT_TEXT_FONT` list — those are all generic Windows system
fonts, fine for basic overlays but not "designed"). He also wants the beat-matched transition
wipes (added in the previous task, `TRANSITIONS_AND_TITLE_REPORT.md`) to carry the *same visual
theme* as the title card, and wants this as a real, reusable app feature (GUI-exposed), not a
one-off manual edit for this specific video.

**Explicit design decision from Tomasz** (asked directly, not guessed): the "AI generation" here
means **local mood/style analysis choosing among curated high-quality presets** — NOT calling an
external image-generation API per render. Everything stays local, consistent with this app's
existing privacy-first architecture (see `SUBJECT_DETECTION_TASK_SPEC.md`'s explicit scoping of
cloud vision APIs off by default for family-footage privacy — the same principle applies here).

## Part 1: Mood signature (no new heavy AI compute — aggregate what's already computed)

This pipeline already computes everything needed to characterize a video's mood; don't add a new
model call, just aggregate existing signals:
- **Emotion tag distribution**: `stage5_qwen_scene_worker.py`'s `ALLOWED_EMOTIONS = {"soft",
  "tension", "hype", "sad", "neutral"}` are already assigned per ai-analyzed clip and land in each
  clip's `tags` in the final plan (confirmed present in prior renders this session, e.g. v4/v5's
  clips carry tags like `beauty`/`clean`/`soft`/`flow`). Aggregate frequency across all
  `ai_analyzed` clips in the render.
- **Audio energy character**: `stage2_features.py`'s `energy wave avg/peak` and `rhythm strength
  avg/peak` (already printed as `Energy wave: avg X, peak Y` / `Rhythm strength: avg X, peak Y` in
  every render's Stage 2 log this session).
- **Section type mix**: `stage3_sections.py`'s section classification (`intro`/`verse`/`chorus`/
  `breakdown`/`finale`, already computed and printed every render).

Combine these into a simple, explainable mood signature (e.g. a 2D score: warmth/sentiment axis
from emotion-tag dominance, energy axis from audio energy avg) — keep the scoring logic simple and
documented, not a black box. This is the "AI" in "AI generation" here: the *selection* is
data-driven, even though the presets themselves are hand-curated (see Part 2).

## Part 2: Three curated visual themes

Bundle real Google Fonts (open-licensed, freely downloadable — fetch the `.ttf` files directly,
e.g. via `web_fetch`/`curl` from `fonts.google.com`/`fonts.gstatic.com`, and store them under a new
`assets/fonts/` directory in the repo, NOT relying on the Windows system font directory like the
existing `_FONTS` list does — this needs to work consistently regardless of what's installed on a
given render box). Each theme bundles: a title font, a subtitle/date font, a color grade tint, a
graphic overlay style for the title card, and a matching tint applied to the beat-matched crossfade
transitions so the wipes visually match the title card (Tomasz's explicit ask — "the wipes should
keep to the same theme").

1. **"Warm & Sentimental"** (dominant emotion `soft`/`sad`, low-moderate audio energy — matches
   this specific footage, a newborn/family video):
   - Title font: **Playfair Display** (elegant serif, bold weight for the name).
   - Subtitle/date font: **Montserrat** (clean geometric sans, light/regular weight).
   - Color grade: warm amber/gold tint (`eq`/`colorbalance` ffmpeg filters, subtle, not garish).
   - Title card graphic: soft bokeh/light-leak overlay (can be procedurally generated via ffmpeg
     `noise`+`gblur`+screen-blend rather than needing external image assets — keep it lightweight).
   - Transition tint: crossfades get a very subtle warm color-temperature shift during the blend
     (not a hard color filter over the whole video — just during the transition blend itself).
2. **"Joyful & Bright"** (dominant emotion `neutral`/`soft` with moderate-high audio energy —
   celebratory/upbeat family moments):
   - Title font: **Quicksand** (rounded, friendly, bold).
   - Subtitle/date font: **Poppins** (clean, warm geometric sans).
   - Color grade: warm pastel/soft-pink-gold tint.
   - Title card graphic: soft floating light-particle overlay.
   - Transition tint: gentle warm light-leak flash during the blend.
3. **"Upbeat & Energetic"** (dominant emotion `hype`/`tension`, high audio energy — action/
   adventure GoPro footage):
   - Title font: **Bebas Neue** (bold condensed display face).
   - Subtitle/date font: **Oswald** (condensed sans, matches the display face family).
   - Color grade: punchier saturated/contrasty tint.
   - Title card graphic: dynamic light-streak overlay.
   - Transition tint: a brief flash/streak during the blend.

Auto-select the theme from the mood signature (Part 1) by default, but the render is against real
data so it's fine if the mapping isn't perfect on the first try — document your exact thresholds in
the report so they can be tuned. **Always allow manual override** (see GUI section) — auto-select
is a convenience default, not a forced behavior.

## Part 3: GUI wiring (required — Tomasz explicitly asked "the app should do this as well")

Add a control to the Create tab in `src/gui.py` following the existing `gr.Radio`/`gr.Dropdown`
patterns already there (e.g. `clip_order_mode`'s Radio): a **"Title Theme"** selector with options
`Auto (AI mood match)` (default) plus the three named themes above, so Tomasz can either let it
pick automatically or force a specific theme. Wire it through the same parameter-threading trail
used for `transitions_enabled`/`title_card_enabled` in the previous task (settings persistence,
`process_video()`, `create_music_video()`, `refine_rerender()`).

## Specific render to verify against

Tomasz wants this exact title for the current project: **"Teresa S. Dunn" / "1st October 2025"**
(name on one line, date on a second line — the existing `start_text` field already supports
multi-line input via `lines=3, max_lines=8` in its `gr.Textbox`, confirmed in `gui.py`; feed it as
`"Teresa S. Dunn\n1st October 2025"` or split into distinct title/subtitle rendering if that reads
better typographically — your call, explain which you chose and why). Given this footage's actual
emotion-tag distribution and low-moderate audio energy (confirmed via every render this session:
dominant tags `beauty`/`clean`/`soft`/`flow`), the auto-select mood match should land on **"Warm &
Sentimental"** — verify this is actually what happens, don't just assert it.

## Verification (real hardware — required)

On `um890` (same setup as prior tasks — venv python, app root, `D:\Photos\GoPro\2025-10-01
Tereska Birth\`, 60s trimmed audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey +
quality-filter + `min_subject_confidence=0.3` baseline, transitions + title card enabled):

1. Render with `start_text` set to the exact title above, theme on `Auto` — confirm via debug log
   or report which theme got selected and why (state the mood-signature scores that drove it).
2. Extract thumbnails from the title card sequence to visually confirm the chosen font/color/
   graphic treatment actually renders correctly (not just that the filtergraph doesn't error).
3. Extract thumbnails from at least one crossfade transition to confirm the theme tint is visible
   there too, not just on the title card.
4. Confirm frame-accurate audio sync is still exactly preserved (same check as the prior task:
   `ffprobe` frame count / duration against the audio track).
5. Confirm genuine AMF hardware encode via `ffprobe` stream tag.
6. Manually force each of the other two themes via the new override and confirm each renders with
   visibly distinct fonts/color grade/graphics (spot-check, doesn't need full renders for all three
   — a quick title-card-only render or thumbnail extraction per theme is enough).

## Constraints

- Primarily touch `src/gui.py`, `src/ffmpeg_processing.py`, `src/video_processor.py`, and add a new
  small module (e.g. `src/title_theme.py`) for the mood-signature and theme-preset logic — keep it
  isolated and readable rather than scattering theme logic across existing files.
- Bundle font files under a new `assets/fonts/` directory, sourced from Google Fonts (open license,
  fine to commit the `.ttf` files directly to the repo — they're small).
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `AI_TITLE_THEME_REPORT.md` in the repo root (same tone/detail as
  `TRANSITIONS_AND_TITLE_REPORT.md`/`JOURNEY_SOURCE_COVERAGE_REPORT.md` in this repo).
- **Commit and push to `origin/main` when done and verified.** Two of the last three tasks this
  session had reports claiming "committed and pushed" when the working tree was still dirty —
  actually run `git status` AND `git log origin/main..HEAD` yourself and confirm both are clean
  before writing "done" anywhere in your report. This is a recurring, known problem — take it
  seriously this time.
