# Addendum to FOCUS_STABILIZE_TINT_TASK_SPEC.md: broaden the focus field into a footage description that also nudges theme selection

Follow-up requirement from the user after reviewing the in-progress focus-hint feature. Do
NOT re-implement the focus/clip-scoring half of FOCUS_STABILIZE_TINT_TASK_SPEC.md — that part
stays as specced (free text -> Qwen `focus_match` -> `_score_candidate()` bonus). This
addendum only broadens what the same field is used for.

## What changes

**Rename/reframe, don't duplicate**: the GUI field stays a single textbox (not two) — relabel
it something like "Describe this footage (optional)" with placeholder text like "e.g. family
coastal holiday, boats and trains, relaxed and nostalgic" rather than the narrower "AI Focus"
framing. Same text value flows to both consumers:

1. Clip-focus scoring — unchanged, as already specced (Qwen `focus_match` per moment).
2. **New**: a nudge to `compute_mood_signature()` in `src/title_theme.py` (~line 130-232),
   which currently derives `warmth`/`energy` (0.0-1.0 each) purely from Qwen emotion-tag
   counts + audio energy/rhythm averages, then a threshold cascade
   (~line 206-227) maps that 2D point to one of the three curated themes.

## How the nudge should work

**Blend, don't override** (explicit user decision — a blank field must reproduce today's
behavior exactly, and even a filled field should shift the automatic signal rather than
replace it outright):

- Derive a rough `(text_warmth, text_energy)` estimate from the description text. Recommend a
  small local keyword lexicon (e.g. "relaxed"/"nostalgic"/"family"/"sentimental" ->
  warmth+; "adventure"/"action"/"exciting"/"energetic" -> energy+; "fun"/"bright"/"playful" ->
  push toward the Joyful & Bright region) rather than an extra LLM call — this keeps theme
  selection instant/deterministic and matches this codebase's existing local-only, no-extra-
  inference-cost design bias. If no lexicon terms match anything in the description, treat the
  text signal as neutral (no nudge) rather than guessing.
- Blend as a weighted average, automatic signal dominant: something like
  `final_warmth = clamp(0.7 * auto_warmth + 0.3 * text_warmth)` (and same for energy), so a
  short/vague description can't wildly override real audio+footage signal, but a clear
  description visibly shifts borderline cases.
- Update `compute_mood_signature()`'s existing explanation string (the `reason` field already
  shown in the render log/GUI, e.g. "Dominant warm/sentimental tags...") to also mention when
  the text description contributed, so the theme choice stays explainable — this app already
  has a convention of printing *why* a theme was picked; preserve that.
- When the field is blank: `text_warmth`/`text_energy` are neutral/no-op, and the blended
  result must be numerically identical to today's `compute_mood_signature()` output (same
  regression-safety requirement as the focus_match feature's blank-field case).

## Verify

- Real render, description blank: theme choice identical to a same-parameters baseline render
  (same theme, same reasoning text).
- Real render, description = "family coastal holiday, boats and trains, relaxed and
  nostalgic": confirm in the render log/report the warmth score shifted upward vs. the
  baseline's automatic score for the same footage, and if that pushes a genuinely borderline
  case across the Warm & Sentimental threshold, confirm the theme actually changes; if it
  doesn't cross a threshold, confirm the *reasoning text* still shows the nudge was applied
  (so the feature's effect isn't silently invisible even when the theme doesn't flip).
- Real render, description = "high energy action adventure": confirm energy score shifts
  upward, ideally on a test case that visibly flips toward Upbeat & Energetic.
