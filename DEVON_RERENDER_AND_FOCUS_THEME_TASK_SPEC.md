# Task: implement the focus-description/theme-blend addendum, then produce a new Devon & Cornwall 2021 render

Two things, in order. Do not skip straight to the render — the addendum must be implemented
and verified first, since the render should exercise it.

## Part 1 — implement `FOCUS_DESCRIPTION_THEME_BLEND_ADDENDUM.md`

Read that file in the repo root and implement it exactly as specced. Summary: the existing
"AI Focus" free-text GUI field (added in `FOCUS_STABILIZE_TINT_TASK_SPEC.md`, commit
`c40e00b`) currently only feeds Qwen's per-clip `focus_match` scoring. Relabel it as a general
footage description ("Describe this footage (optional)") and additionally derive a rough
`(text_warmth, text_energy)` signal from it via a small local keyword lexicon (no extra LLM
call), blended into `compute_mood_signature()` in `src/title_theme.py` as
`final = clamp(0.7*auto + 0.3*text)`, auto-dominant. Blank field must reproduce today's
`compute_mood_signature()` output byte-identical (regression requirement). Update the theme's
`reason` explanation string to mention the text nudge when one was applied. Full detail,
including the exact blend formula and verification cases, is in the addendum file — follow it,
not this summary.

Verify per the addendum's own "Verify" section (blank-field regression, a warm/nostalgic
description shifting warmth up, an energetic description shifting energy up) using this
project's normal standard: real render(s) on `um890` (`ssh um890`), not just unit tests.
`git status`/`git log origin/main..HEAD` after claiming done, and paste the *actual* output in
your report — this repo's history shows CAO workers have repeatedly claimed "committed and
pushed" before it was true; don't repeat that.

## Part 2 — new Devon & Cornwall 2021 render

Source footage: `D:\BeatSync\SourceCache\Devon & Cornwall 2021\` on `um890` (44 Canon C300
clips, 1920x1080, remuxed mp4). A prior render
(`D:\BeatSync\Output\Devon & Cornwall 2021\devon_cornwall_2021_20260925_125928.mp4`) was made
*before* the `c40e00b` tint-flick/stabilize/focus-hint fix landed, and had a real visible
ghosting/double-exposure artifact at crossfade boundaries between visually-similar static
shots (confirmed directly — extracted frame at t=10.0s of that render shows a duplicated
gantry structure ghosted over the main frame; adjacent frames at t=9s/11s are clean). That
render also has at least one selected clip with severe motion blur (~t=42s) that reads as a
"funny shot" to a viewer — worth a look during Part 2's QA pass (Layer 1 quality filter may
need a second look for this footage's blur characteristics vs. the GoPro footage it was tuned
against; MAX_CLIP_LENGTH/QUALITY_FILTER specs already in this repo's history are the relevant
prior art if a real gap is confirmed — don't invent a new mechanism if the existing one just
needs its threshold checked against this specific clip).

Render via the GUI's `process_video()` function directly (same approach used throughout this
repo's history — see `AI_TITLE_THEME_REPORT.md` etc.), same settings as the prior render
(landscape 1920x1080, h264_amf, journey mode, quality filter on, transitions + title card on,
theme auto), PLUS:
- Footage description field (new from Part 1): `"family coastal holiday, boats and trains,
  relaxed and nostalgic"`.
- Use the same audio track as the prior render if it's still present on the box
  (`C:\BeatSyncTest\looking_into_the_future.mp3` — check it exists; if not, ask by leaving a
  clear note in your report rather than substituting a different track silently).
- Title text: `"Devon & Cornwall"` / `"August 2021"` (matches the prior render's own title
  card, seen directly).

Output to `D:\BeatSync\Output\Devon & Cornwall 2021\` with a new timestamped filename (don't
overwrite the prior render — keep it as a before/after reference).

**QA before calling this done** — reuse the same technique used to find the original bug:
extract frames via ffprobe/ffmpeg at a handful of crossfade boundaries (check the plan JSON's
`transitions` list for boundary timestamps) plus a few ordinary mid-timeline points, and
confirm no ghosting/tint-flick and no severe-blur clips remain. Report which timestamps you
checked and what you saw — not just "looks fine."

Send a compressed preview (480p or similar, well under 30MB) somewhere retrievable, and note
the full 4K output's path on `um890` in your report, same convention as every prior render in
this repo's history.

## Constraints
- Working directory: `/home/pi/projects/BeatSync-Engine` on Jarvis, hardware verification via
  `ssh um890`.
- No deletions of the prior render or any source footage.
- Don't touch `CLAUDE.md`/`AGENTS.md`.
- Write a report file (`DEVON_RERENDER_AND_FOCUS_THEME_REPORT.md`) covering both parts, commit
  and push, and paste real `git status`/`git log origin/main..HEAD` output in the report as
  proof, not a placeholder.
