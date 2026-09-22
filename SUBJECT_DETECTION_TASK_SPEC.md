# Task: filter out no-subject / pocket / floor shots from candidate selection

## Problem
Reported by Tomasz after a real render (`output/music_video_20260922_171820.plan.json`,
GoPro footage from a family event): the final video includes "dead" shots — floor, and
clips clearly filmed from inside a pocket — mixed in with real footage of people.

Root cause, confirmed by reading the scoring pipeline (`src/video_analysis.py`):
- `_build_candidate()` (~line 1206) and `_fallback_tags()` (~line 1278) score every
  candidate window on sharpness, darkness, motion, colorfulness/saturation. A well-lit,
  non-blurry shot of a floor or the inside of a pocket scores *fine* on all of these —
  nothing in the deterministic metrics evaluates scene content.
- There is already a local vision-LLM pass (`_annotate_candidates_with_qwen()` ~line 1323,
  worker at `src/auto_mode/stage5_qwen_scene_worker.py`, runs Qwen via llama.cpp/Vulkan on
  the box's own GPU — no external API, nothing leaves the machine). Its prompt
  (`_build_prompt()`, stage5 worker ~line 271) is written entirely for action-movie
  AMV/GMV tagging: `action_intensity, beauty_score, combat, chase, explosion,
  character_focus, camera_motion, visual_quality, emotion, recommended_use`. Nothing in
  that schema asks whether a *subject is even visible in frame*, so it can't catch this
  either. It's only run on a capped subsample per video (`BEATSYNC_QWEN_MAX_WINDOWS`,
  default 120), not every candidate.

This is a real content gap, not a tunable parameter — needs new signal, not a threshold
tweak on existing scores.

## Fix — two layers, both local/free, no cloud API calls by default

### Layer 1: cheap deterministic pre-filter (every candidate, every video)
Add a lightweight local person/subject detector run on the same sample frames already
being decoded in `_measure_window()`/`_measure_frame_samples()` (~line 1031/1051) — reuse
the existing frame reads, don't re-decode. Use a small pretrained detector (e.g. a
few-MB YOLOv8n or MobileNet-SSD ONNX model, CPU-fast, no GPU required) to produce a
`subject_confidence` (0..1) per candidate window: does the sampled frame contain a person
(or, more loosely, any clear foreground subject vs. blank floor/ceiling/pocket-darkness).
Store this as a new field on the candidate dict alongside `action_score`/`beauty_score`/etc.

This layer alone should catch the obvious pocket/floor cases cheaply, without touching the
Qwen budget.

### Layer 2: extend the existing local Qwen pass for the harder/ambiguous cases
Since Qwen already looks at a sampled frame per candidate it processes, extend its JSON
schema (`_build_prompt()` in `stage5_qwen_scene_worker.py`) with two new keys:
- `subject_visible` (0..1)
- `framing_issue` — one of `none, floor, pocket, sky, blank, motion_blur`

Merge these into `_merge_semantic()` (`video_analysis.py` ~line 1464) the same way
`character_focus`/`camera_motion` etc. are merged today.

### Scoring integration
Add a `min_subject_confidence` GUI setting (default lenient/off, so establishing/scenery
shots users *do* want aren't nuked by default) — a slider or checkbox "Filter shots with
no visible subject". When enabled, candidates below threshold from Layer 1 (and, if
Qwen ran on that window, Layer 2) are down-ranked hard or excluded outright, not just
soft-weighted — a floor shot should not be able to outscore a real person-shot no matter
how sharp/well-lit it is.

## Explicitly NOT in scope for this task
Do **not** default to calling an external vision API (Claude/GPT/etc.) for this. This
pipeline runs on Tomasz's own personal/family footage — routing
frames through a third-party cloud API is a privacy decision only he should opt into
explicitly, and the local Qwen path already covers the same capability for free. If you
believe local-model accuracy is insufficient after testing, stop and flag it in the
report rather than wiring in a cloud call — don't add one silently.

## Verification (do not skip — see project history)
Past changes to this repo that were "should work"/syntax-checked but not run on real
hardware have hidden real bugs each time (DXVA2 `-hwaccel auto` crash, Gradio `.input()`
API mismatch, NVENC false-positive that silently hid the AMD option entirely). Test this
change against a real source folder containing obvious pocket/floor shots (the footage
that surfaced this bug — ask Tomasz for the current folder path) with the new filter
enabled, and confirm via the render's
`.plan.json` that pocket/floor-tagged candidates are actually excluded/down-ranked while
genuine people-shots are not accidentally dropped too. Report false-positive/false-negative
examples you find, don't just assert it works.

## Report
Write findings to `SUBJECT_DETECTION_REPORT.md` in repo root when done, same format as
`AMD_AMF_REPORT.md`.
