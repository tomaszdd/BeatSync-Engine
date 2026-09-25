# Task spec: AI focus hint, outdoor stabilization, crossfade-tint flick fix

Three real issues found reviewing a real render (`Devon & Cornwall 2021`, a travel-footage
edit from Canon C300 MXF source, remuxed to mp4, journey mode, transitions on, Warm &
Sentimental theme auto-selected). Root causes below are confirmed by direct inspection —
implement fixes against them, not guesses.

## 1. Crossfade tint "flick" — real bug, root-caused

`add_text_overlays_ffmpeg`/transition-assembly code in `src/ffmpeg_processing.py`
(~line 1685-1750) applies a themed color grade during each crossfade blend:

```python
theme_tint = theme_preset.transition_tint_eq if (theme_preset and hasattr(theme_preset, 'transition_tint_eq')) else None
...
f"{xf_raw}eq={theme_tint}:enable='between(t,{offset:.4f},{offset+d:.4f})'{next_stream}"
```

For Warm & Sentimental this is `eq=gamma_r=1.12:gamma_b=0.88:saturation=1.06` (see
`src/title_theme.py` ~line 92) — a real amber/yellow push. The `enable='between(...)'` gate
turns the eq filter fully on/off with no ramp, so at every crossfade boundary (48 in the
test render) there's an abrupt color step for the 0.35s blend duration — visible in playback
as a "flick", confirmed by the user watching a real render, not a subjective theme complaint.

**Fix**: replace the hard on/off gate with a smooth envelope so the tint eases in and back
out across the blend window instead of stepping. FFmpeg's `eq` filter supports per-frame
time-varying expressions when `eval=frame` — use a smoothstep-style envelope keyed to `t`
relative to `offset`/`offset+d` (peaking mid-blend, zero at both edges), similar in spirit to
the existing crop-ease smoothstep work already in this codebase
(`build_crop_to_fill_filter()` in `src/ffmpeg_processing.py` — reuse that
`min(1\,t/E)`-style escaping lesson, a bare comma in an eq expression will truncate the
filtergraph exactly like it did there). Apply the same envelope treatment to all three theme
presets' `transition_tint_eq`, not just Warm & Sentimental.

Verify by rendering a real multi-crossfade test and pulling frames at several boundaries
across the *whole* timeline (not just early ones) to confirm no visible flash step, plus the
usual zero-drift/frame-count check this codebase already does for transition work.

## 2. Outdoor shot stabilization

No stabilization exists anywhere in the pipeline (confirmed via grep). The ffmpeg build in
`bin/ffmpeg/` has `--enable-libvidstab` compiled in (confirmed:
`vidstabdetect`/`vidstabtransform` both present in `ffmpeg -filters`).

**Add**: a GUI checkbox ("Stabilize Shaky Footage" or similar, default off) that runs the
standard two-pass vidstab (`vidstabdetect` pass writing a transform-log per source clip
during extraction, then `vidstabtransform` applied in the same filtergraph as the existing
crop/scale/AMF-encode chain) on every extracted clip when enabled. Thread it through
`_process_video_impl`/`process_video` in `src/gui.py` and persist it via the existing
`_SETTINGS_KEYS`/`_settings_components` mechanism, same pattern as `transitions_enabled`
etc. Keep it a single global toggle (all clips), not per-clip shake detection — simpler,
and the user asked for "outdoor shots" generally, not a shake-detector.

Verify: render a test with a source clip that's visibly handheld/shaky, confirm output is
visibly steadier; confirm a locked-off tripod shot (e.g. the level-crossing footage in this
same source folder — see #3) isn't degraded by the process; confirm frame-accurate sync and
AMF encode still hold with the extra filter in the chain (extraction time will increase —
vidstabdetect is a real second decode pass — report actual added render time).

## 3. AI "Focus" hint — the real fix for both "nothing happening" AND "feature this subject"

Reviewing the actual plan.json + real frames from the test render: the first ~16s of that
render is six different source files (A006C002 through A006C007) that are literally all the
same static tripod shot of a level crossing waiting for a train — a real "nothing happening"
stretch. A train actually does pass through at ~16s in the underlying footage (confirmed in
`A006C007_210811TI_CANON.mp4`), but the planner only used ~1.5s of it. Separately, the user
wants specific recurring subjects (boats/ferries arriving, in this case) to get more
prominence, but said explicitly he wants this as a general "tell the AI what to concentrate
on" feature, not a one-off manual pin of two clips.

**Add a free-text "Focus" GUI field** (e.g. label "AI Focus (optional)", placeholder like
"boats and trains arriving") that flows through to Qwen semantic tagging and candidate
scoring:

- `_build_prompt()` in `src/auto_mode/stage5_qwen_scene_worker.py` (~line 281) takes an
  optional `user_focus: str` and, when non-empty, adds to the prompt something like: "The
  editor especially wants moments showing: {user_focus}. If this moment clearly shows that,
  set focus_match to a high value (close to 1); otherwise low." Add `focus_match` (0..1) to
  the returned JSON schema alongside the existing `action_intensity`/`beauty_score`/etc
  keys, validated the same way the other numeric fields are in `_normalize_semantic`.
- Thread `user_focus` from the GUI through wherever `_build_prompt`/the Qwen worker gets
  invoked (check both the call site in `stage5_qwen_scene_worker.py`'s job runner and
  anywhere `audio_profile` is built) down from `_process_video_impl` in `src/gui.py`.
- Merge `focus_match` into the semantic dict the same way `framing_issue` is merged in
  `src/video_analysis.py` (~line 1577-1581).
- In `_score_candidate()` in `src/auto_mode/stage6_av_planner.py` (~line 1244), add a
  `focus_bonus` term (e.g. `0.20 * focus_match`, tuned so it can meaningfully outweigh a
  merely-adequate score but doesn't override genuinely broken footage — respect the existing
  `visibility_penalty`/quality floor) so high-`focus_match` candidates are preferred within
  their target bucket, not force-inserted regardless of beat/section fit.
- Persist the field via `_SETTINGS_KEYS`/`_settings_components` like every other setting.
- When the focus field is blank (the common case), behavior must be byte-identical to
  today — this is opt-in, not a default-on rescoring change.

This is deliberately generic rather than special-casing "trains" or "boats" — the user's own
framing was "a comment box for the LLM to focus on... so it knows what to concentrate on",
not a specific hardcoded subject list.

**Verify** against this exact real source folder
(`Z:\Photos\_Stephen Photos\Devon_Cornwall_Aug2021\CONTENTS\CLIPS001`, or the already-remuxed
local copy if still present in `D:\BeatSync\SourceCache\Devon & Cornwall 2021\` on `um890`)
with a focus string like "boats and ferries arriving, trains passing through the level
crossing" — confirm via the plan.json that clips from `A006C023` (the "Hauley V" boat) and
`A006C043` (the "Aries 3" bridge scene) get more/longer usage than in the baseline render,
and that the ~16s dead static-crossing stretch shrinks in favor of the moment the train is
actually visible. Dump before/after clip counts per source file in the report, same style as
the journey-source-coverage report's before/after proof.

## General

- Standard practice for this repo applies: git-verify your own "committed and pushed" claims
  with `git status`/`git log origin/main..HEAD` before writing them in the report — recent
  history in this project (see `project_beatsync_amd_amf.md` memory if available) shows this
  claim has been wrong more than once.
- Test on real hardware (`um890`, `172.30.40.186`) — this project has a standing rule that
  untested filtergraph/pipeline claims are not trustworthy (multiple real bugs this session
  were only caught by an actual render, not code review).
- `output_folder`/per-project-subfolder support already exists in this repo
  (`get_output_dir()`/`set_output_dir()` in `src/paths.py`, `_derive_project_folder_name()`
  in `src/gui.py`) — use it as-is, no changes needed there.
