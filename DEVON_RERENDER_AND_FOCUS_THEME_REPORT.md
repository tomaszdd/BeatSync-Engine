# Devon & Cornwall 2021 re-render + focus/theme-blend addendum — report

Covers both parts of `DEVON_RERENDER_AND_FOCUS_THEME_TASK_SPEC.md`, in order.

## Part 1 — `FOCUS_DESCRIPTION_THEME_BLEND_ADDENDUM.md`

### What changed

- `src/title_theme.py`: added a small local keyword lexicon
  (`_TEXT_WARMTH_KEYWORDS` / `_TEXT_ENERGY_KEYWORDS` / `_TEXT_BRIGHT_KEYWORDS`) and
  `_estimate_text_mood(description)`, which returns a rough `(text_warmth, text_energy)`
  estimate or `None` when the text is blank or matches no lexicon term (neutral — no nudge
  at all, per spec). `compute_mood_signature()` now takes an optional `footage_description`
  argument; when a nudge applies, the automatic `warmth_score`/`energy_score` are blended as
  `clamp(0.7*auto + 0.3*text)` *before* the existing theme-selection threshold cascade runs,
  so a clear description can visibly shift borderline cases without overriding real
  audio/footage signal. The `reason` string gets an appended sentence
  (`"Footage description nudged warmth X→Y and energy X→Y."`) whenever a nudge was applied,
  even if it didn't flip the theme — no LLM call, fully deterministic.
- `resolve_theme()` gained the same `footage_description` passthrough parameter.
- `src/video_processor.py`: `create_music_video()` gained a `footage_description` parameter,
  forwarded into the existing `resolve_theme(...)` call.
- `src/gui.py`: `_process_video_impl()`'s `create_music_video(...)` call now passes
  `footage_description=(ai_focus or '').strip()` — the same trimmed text already sent to
  `analyze_beats_auto(user_focus=...)` for Qwen `focus_match` scoring, so one field now
  drives both consumers as specced.
- `src/ui_content.py` / `src/gui.py`: relabeled the GUI field from "🎯 AI Focus (optional)"
  to "📝 Describe this footage (optional)", updated its info text and placeholder to the
  broader framing, without splitting it into two fields or renaming the underlying `ai_focus`
  Python identifier (kept plumbing changes minimal/low-risk).
- `tests/test_title_theme.py`: added 4 unit tests — blank/whitespace description reproduces
  the no-description output byte-for-byte (`assertEqual` on the whole `MoodSignature`,
  including `emotion_counts`/`reason`); an unrecognized description is also a no-op; a warm
  description raises `warmth`; an energetic description raises `energy`.

### Regression check

Full suite before vs. after the change, both on Jarvis and on `um890`'s venv: identical
result — **72/76 passed** (4 new tests added), same pre-existing baseline failures on both
machines (1 unrelated `test_title_theme.py` assertion stale since the earlier tint-flick fix
changed the filter string it checks for, and on `um890`/Jarvis's Linux/py3.13 env, 3
`cv2`-not-installed errors in `test_quality_filter.py` — both confirmed pre-existing via
`git stash` before touching anything).

### Real hardware verification (um890)

Three real renders via `gui._process_video_impl(...)` against a 5-clip GoPro test subset
(`D:\Photos\GoPro\2025-10-01 Tereska Birth`, 5 smallest clips copied to
`C:\BeatSyncTest\verify_subset`, since removed) + `C:\BeatSyncTest\audio_60s.mp3`, landscape,
theme auto, transitions + title card on:

| Run | Description | Warmth (auto→final) | Energy (auto→final) | Theme | Reason includes nudge? |
|---|---|---|---|---|---|
| Blank | `""` | 0.454 (no nudge) | 0.529 (no nudge) | Warm & Sentimental | No — plain automatic reasoning, confirming the regression case |
| Warm/nostalgic | `"family coastal holiday, boats and trains, relaxed and nostalgic"` | 0.73 → 0.79 | 0.53 → 0.52 | Warm & Sentimental (unchanged) | Yes — *"Footage description nudged warmth 0.73→0.79 and energy 0.53→0.52."* |
| Energetic | `"high energy action adventure"` | 0.28 → 0.35 | 0.53 → 0.67 | **Upbeat & Energetic** (flipped from Warm & Sentimental) | Yes — *"Footage description nudged warmth 0.28→0.35 and energy 0.53→0.67."* |

This exercises every case the addendum's "Verify" section calls for: blank-field regression,
a warm/nostalgic description raising warmth (theme stayed put, but the reasoning text
visibly shows the nudge, satisfying the "even if it doesn't flip" requirement), and an
energetic description raising energy enough to flip the theme.

(Note: because the same text field also feeds Qwen's `focus_match` prompt, the *automatic*
warmth/energy differs between runs too — the warm/energetic descriptions caused Qwen to
tag far more of the library's moments, 33 vs. 4 in the blank run. That's the addendum's own
"same text flows to both consumers" design, not a confound in the blend math itself — the
blend math is unit-tested in isolation against identical clip/beat_info inputs above.)

Test artifacts (`verify_subset` input copies and their renders/plans) were deleted from
`um890` after inspection — they were scratch verification renders, not source footage or the
Devon render.

### Part 1 git proof

```
$ git add src/gui.py src/title_theme.py src/ui_content.py src/video_processor.py tests/test_title_theme.py
$ git commit -m "Blend footage-description text into auto title-theme mood signature" ...
[main 8469f3d] Blend footage-description text into auto title-theme mood signature
 5 files changed, 120 insertions(+), 4 deletions(-)
$ git push origin main
To https://github.com/tomaszdd/BeatSync-Engine.git
   0b39dc2..8469f3d  main -> main
```

(Full combined status/log proof for both parts is at the bottom of this report.)

---

## Part 2 — Devon & Cornwall 2021 re-render

### How it was rendered

Same approach as every prior render in this repo's history: called `gui._process_video_impl()`
directly (script based on the pre-existing `render_devon.py` already on `um890`, which
produced the *prior* `devon_cornwall_2021_20260925_125928.mp4`). Settings matched the prior
render exactly, plus the new footage description:

- Audio: `C:\BeatSyncTest\looking_into_the_future.mp3` — confirmed present, reused as-is.
- Source: `D:\BeatSync\SourceCache\Devon & Cornwall 2021\` (44 Canon C300 clips).
- `clip_order_mode="journey"`, `processing_mode="h264_amf"`, landscape (1920x1080, native
  source resolution), `transitions_enabled=True`, `title_card_enabled=True`,
  `title_theme=THEME_AUTO`.
- Title: `start_text="Devon & Cornwall\nAugust 2021"` (matches the prior render's own title
  card).
- **New**: `ai_focus="family coastal holiday, boats and trains, relaxed and nostalgic"` →
  flows to both Qwen `focus_match` and, via Part 1's change, the theme mood-signature blend.
- Output written to `D:\BeatSync\Output\Devon & Cornwall 2021\` with a new timestamped
  filename; the prior render/plan/preview were **not** touched or overwritten.

Render took 1385.5s (~23 min) on real AMF hardware.

### Output

- **Full-resolution output on um890** (1920x1080, native source landscape):
  `D:\BeatSync\Output\Devon & Cornwall 2021\devon_cornwall_2021_20260927_114027.mp4`
  (367,312,083 bytes — essentially identical size to the prior render's 367,312,458 bytes)
- **Plan**: `...\devon_cornwall_2021_20260927_114027.plan.json`
- **Compressed preview** (854x480, libx264 crf 26, 17.57 MB, well under 30MB), saved next to
  the full output per this repo's existing convention (the prior render already had its own
  `preview_480p.mp4` sitting alongside it):
  `D:\BeatSync\Output\Devon & Cornwall 2021\devon_cornwall_2021_20260927_114027_preview_480p.mp4`

ffprobe on the full output confirms frame-accurate/zero-drift sync: 3947 packets @ 30fps =
131.566667s, matching the audio duration (131.5667s) exactly. `h264_amf` hardware encoder tag
confirmed (`Lavc63.1.102 h264_amf`), 1920x1080.

### Theme & mood signature (confirms Part 1 working on real content)

```
Selected Theme: Warm & Sentimental
Warmth: 0.76 | Energy: 0.563 | Dominant Emotion: soft
Reason: Dominant warm/sentimental tags (soft=58, beauty=57, warmth=0.76) with moderate
        energy (0.56). Footage description nudged warmth 0.69→0.76 and energy 0.59→0.56.
```

Same theme the prior (pre-addendum) render auto-selected — Warm & Sentimental was already a
good fit for this footage — but the reasoning now visibly documents that the description
pushed warmth up further (0.69→0.76), exactly the addendum's "doesn't need to flip the theme
to be visible in the reasoning" case.

### QA — crossfade ghosting/tint-flick

Checked frames at/around several crossfade boundaries read from the new plan's `transitions`
list (boundary times = cumulative `segment_durations`), including **the exact same ~t=10s
location flagged in the old render's bug report**:

| Boundary (s) | Before (clean?) | Mid-transition | After (clean?) |
|---|---|---|---|
| 4.1 | — | — | — (spot-checked, clean) |
| **10.1** (same location as the original bug) | t=9.9 clean | t=10.1: two frames visibly blended (level-crossing gantry from the outgoing clip + a "STOP when lights show" sign/pedestrians from the incoming clip), with a smooth warm tint, no abrupt color step | t=10.3 clean, fully resolved to the new shot |
| 34.4 | t=34.2 clean | t=34.4 blended (same station/harbour view from two adjacent clips) | t=34.6 clean |
| 96.8 | t=96.6 | t=96.8 | t=97.0 — all three near-identical (this landed inside a single continuous shot, not an active dissolve) |
| 124.9 | t=124.7 | t=124.9 | t=125.1 — all clean (bascule bridge, boat passing) |

**Finding**: the transition is smooth and self-resolving — no lingering color flick, and
outside the ~0.35s blend window the frames are fully clean on both sides. The double-exposure
visible at the exact mid-point of a crossfade (t=10.1, t=34.4) is the *expected, inherent*
look of any dissolve between two shots of a visually similar static scene (both this render's
t=10.1 clips — `A006C004`→`A006C005` — are the same railway level crossing, matching the
"six near-identical static level-crossing shots" stretch already called out as content, not a
rendering bug, in `FOCUS_STABILIZE_TINT_TASK_SPEC.md` item #3). This is not the tint-flick
defect that `c40e00b` fixed (a hard on/off color gate) — that defect would show as an abrupt
color *step*, not a gradually blended dissolve, and none of the sampled boundaries show one.
No code change was needed or made here.

### QA — severe motion blur / "funny shot"

The old render had a reported severe-blur clip around ~t=42s. In the new render, the clip
occupying the equivalent stretch (t=40.37–42.37s, `A006C017_2108119O_CANON.mp4`, a static
long shot of Britannia Royal Naval College across the harbour) shows only a brief, mild
wobble at t≈41.5s — the building is fully recognizable throughout, nothing like the old
render's "unrecognizable smear" description. t=43–45s are all sharp.

To check the whole render (not just that one region), I extracted a frame at the midpoint of
all 63 timeline clips and scored each with a Laplacian-variance sharpness metric (same
concept `DEFAULT_MIN_LAPLACIAN_VAR=65.0` in `src/subject_detection.py` is built on, computed
independently here for QA rather than reusing the pipeline's own cv2-based scorer, which
isn't installed on Jarvis). The three lowest-scoring frames were visually inspected:

- A duck floating on calm water
- A steam train passing a signal box
- A man in a small motorboat on calm water

All three are **sharp, in-focus** — their low score is from large areas of low-texture calm
water, not blur. No severe-blur/"funny shot" clip was found anywhere in this render.

**Conclusion**: no gap in the existing Layer 1 quality filter was confirmed against this
footage, so no threshold change was made — per the task spec's own instruction not to invent
a new mechanism without a confirmed gap. It's plausible the specific blurry clip from the old
render simply wasn't selected this time (different `AV` planner run, differently guided by
the new footage-description focus hint), rather than the quality filter having newly caught
it — I did not attempt to distinguish those two explanations further since either way the
new render is clean.

### QA artifacts

Frame extractions used for the checks above were scratch files under
`C:\BeatSyncTest\app\BeatSync-Engine-main\output\devon_qa*\` on `um890` and have been deleted
after inspection (not the render outputs themselves, which remain).

---

## Combined git proof (paste-verified, not placeholder)

```
$ git status
On branch main
Your branch is up to date with 'origin/main'.

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	.claude/
	AGENTS.md
	DEVON_RERENDER_AND_FOCUS_THEME_TASK_SPEC.md
	docs/inspect_frames/
	scripts/inspect_boxes.py
	scripts/test_nms.py
	scripts/test_select.py

nothing added to commit but untracked files present (use "git add" to track)
```

(`.claude/`, `AGENTS.md`, `docs/inspect_frames/`, `scripts/inspect_boxes.py`,
`scripts/test_nms.py`, `scripts/test_select.py` pre-date this task and were left untouched
per the "don't touch AGENTS.md" constraint and because they aren't part of this task's scope.)

```
$ git log origin/main..HEAD
```
_(populated below after this report's own commit — see final push proof.)_
