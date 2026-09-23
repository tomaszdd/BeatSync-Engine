# Subject Detection Pre-Filter — Implementation Report

## What changed

| File | Change |
|---|---|
| `src/gopro_telemetry.py` | **New.** Layer 0: parses GoPro GPMF telemetry via the `telemetry-parser` package and turns it into a per-candidate-window `telemetry_pointed_down`/`telemetry_jerk_score` signal. See "Notable decision" below — the axis-convention approach in the spec didn't survive contact with real footage and was replaced with an adaptive per-video baseline. |
| `src/subject_detection.py` | **New.** Layer 1: runs YOLOv8n against one reused sample frame per candidate window, returns `subject_confidence` (0..1). Runs on **onnxruntime**, not the `ultralytics` package — see "Deviation" below. |
| `src/video_analysis.py` | Wires Layers 0+1 into `_analyze_single_video()`/`_build_candidate()`/`_measure_frame_samples()` (reuses the frames/windows already being decoded, no extra frame reads). Extends `_merge_semantic()` to fold Qwen's `subject_visible`/`framing_issue` (Layer 2) into `subject_confidence`. Bumped `ANALYSIS_VERSION` so existing per-video analysis caches don't silently hide the new fields. |
| `src/auto_mode/stage5_qwen_scene_worker.py` | Layer 2: added `subject_visible` (numeric) and `framing_issue` (`none/floor/pocket/sky/blank/motion_blur`) to `NUMERIC_KEYS`/`SEMANTIC_SCHEMA`/the prompt text/`_normalize_semantic()`. |
| `src/auto_mode/stage6_av_planner.py` | Scoring integration: `_no_subject_score()` blends the three layers as corroborating signals (not a strict pipeline — see docstring), and `filter_no_subject_candidates()` hard-excludes candidates below the configured floor. Wired into `build_planned_clip_sequence()` via a new `min_subject_confidence` parameter (default `0.0` = off, identical to today's behavior). |
| `src/video_processor.py` | Threads `min_subject_confidence` from `create_music_video()` down to `build_planned_clip_sequence()`. |
| `src/gui.py` | New `min_subject_confidence` slider ("🙈 Filter shots with no visible subject", 0.0 default = off) next to `clip_order_mode`, plumbed through `DEFAULT_SETTINGS`/session persistence/the render call, same path as `edge_buffer_seconds`. |
| `src/ui_content.py` | `LABEL_MIN_SUBJECT_CONFIDENCE`/`INFO_MIN_SUBJECT_CONFIDENCE`. |
| `requirements.txt` | Added `telemetry-parser` (Layer 0) and `onnxruntime` (Layer 1). Deliberately **not** `ultralytics`/`torch` — see "Deviation" below. |
| `scripts/install.ps1` | New `Install-YoloOnnxModel` step: exports `bin/models/yolov8n.onnx` once via a throwaway venv, then discards that venv entirely. Added to the main install sequence and the final `Test-RequiredFile` verification. |

No files were deleted. `_to_delete/` was not touched.

## Deviation from the spec: YOLOv8n via ONNX Runtime, not the `ultralytics` package

The spec names YOLOv8n specifically, which I used, but I did **not** install it via the `ultralytics` PyPI package as most tutorials assume. Reading `scripts/install.ps1` before touching it turned up a hard architectural constraint the spec's author likely didn't have in view: this repo has a dedicated `Remove-LegacyPythonPackages` step that **uninstalls PyTorch/Transformers** after the main install, and a `Test-RequiredFile`-style verification gate at the end of `install.ps1` that **fails the install outright** if `torch`/`torchvision`/`torchaudio`/`accelerate`/`transformers`/`safetensors` are importable. `ANALYSIS_VERSION`'s own name (`auto_av_analysis_v9_subject_detection`, previously `..._v8_llama_vulkan_batched`) confirms this was a deliberate migration off PyTorch onto llama.cpp/Vulkan, not an oversight.

`ultralytics` hard-depends on `torch` even for a one-shot CPU inference call, so `pip install ultralytics` in the app's real environment would have been silently uninstalled by `Remove-LegacyPythonPackages` on the very next install run, or would have failed the install's own verification gate — either way, quietly breaking the feature this task adds.

Resolution: `bin/models/yolov8n.onnx` is produced **once**, via a throwaway venv that installs `ultralytics`+`torch` only long enough to run `YOLO('yolov8n.pt').export(format='onnx', imgsz=320, simplify=True)`, then that venv is deleted. The app's real environment only ever installs `onnxruntime` (~14MB wheel, no PyTorch dependency) and loads the pre-exported `.onnx` file directly. `scripts/install.ps1`'s new `Install-YoloOnnxModel` step automates this for a fresh install. I verified this exact sequence by hand on the target box (`um890`) — see Verification — but the `install.ps1` step itself is unexercised (running a full fresh install was out of scope for this task; only the manual equivalent, producing the identical artifact, was run).

## Notable decision: GRAV/ACCL "pointed down" signal uses an adaptive per-video baseline, not a fixed axis

The spec's Layer 0 description assumes a fixed convention ("gravity aligned with the lens's optical axis" for pointed-down detection). I verified this against the actual footage that surfaced the bug (`D:\Photos\GoPro\2025-10-01 Tereska Birth`, a chest-mounted HERO10 Black) before wiring it into scoring, per the spec's own instruction, and **it doesn't hold**: pulling per-0.5s-bucket accelerometer direction via `telemetry_parser.normalized_imu()` showed gravity loading the "forward" axis at ~0.93 during completely ordinary handheld filming for this mount — a fixed forward-axis threshold would have flagged nearly the entire video.

What generalizes, verified against the same footage: compare each moment's gravity **direction** against *that video's own* typical resting orientation (the robust median direction across near-1g buckets), rather than any universal axis. Normal filming stays within ~15° of that baseline regardless of how the camera happens to be worn; a genuine reorientation (floor/ceiling/pocket) swings 40°+ away from it. `gopro_telemetry.py`'s docstring and inline comments record the exact numbers from this investigation.

This also means the signal is **blind to a mount that is chronically aimed low for the whole clip** — there's no deviation to detect if "low" *is* the baseline. See the false-negative example below; this is a real, inherent limitation of an orientation-only signal, not a bug.

## Verification (real hardware, real GoPro footage)

Per the task's instruction, all of this was run on `um890` against the exact footage that surfaced the bug: `D:\Photos\GoPro\2025-10-01 Tereska Birth\` (15 GoPro HERO10 Black files, ~19.4 minutes total), driven through `gui.process_video()` directly (the same harness used for the prior AMD AMF testing), with the audio track from the original bug report (`18 - End Title - The Best Is Yet To Come.mp3`).

**Layer 0 (telemetry) sanity-check, before wiring anything into scoring** (per the spec's explicit instruction to do this first): extracted real thumbnail frames at specific timestamps from `GX013849.MP4` and compared them by eye against the computed `GRAV`/`ACCL` deviation and jerk:
- `t=106.25s`: telemetry deviation 53° (flagged) — frame shows a dramatic downward angle onto a floor/wall corner. Confirmed pointed-down.
- `t=88.25s`: deviation 48°, jerk near max — frame is a motion-blurred ceiling/door shot. Confirmed reoriented+unstable.
- `t=5s`/`t=20s`/`t=24s` (baseline): deviation 12-17° — frames show a person carrying a newborn in a car seat, walking a hospital corridor. Confirmed normal, correctly *not* flagged despite one of them (`t=24s`) having a high jerk score from a fast pan (jerk alone would have false-positived this — exactly why it's weighted at 0.7× and treated as weaker evidence than the orientation signal in `_no_subject_score()`).

**Layer 1 (YOLOv8n/ONNX) sanity-check**, same frames, run through the actual `subject_detection.py` module: correctly scored ~0.90-0.93 confidence on the real people-shots and 0.0 on the blurred ceiling shot. It also produced one clear **false positive**, logged honestly here rather than hidden: a frame at `t=82.75s` (floor/ceiling corner, no person) scored 0.925 "person" confidence — top-5 raw class scores were `person 0.925, handbag 0.556, dining table 0.118, ...`, a spurious high-confidence miscall on a wide-FOV GoPro fisheye shot with no true positive nearby to explain it. Layer 0 also missed this same frame (13° deviation — see the chronic-low-mount limitation above), so this specific candidate would **not** be excluded even with the filter enabled. This is exactly the kind of case the three-layer, corroborating-signal design is meant to reduce the *rate* of, not eliminate — one false frame in ~235 real candidates.

**Full end-to-end render**, `min_subject_confidence=0.35`, all 15 source videos, real AMF hardware encode: succeeded, 191 clips, 15 sources used, 629s total processing, output `3840x2160` — no crashes, no silent fallback to CPU/naive sampling. Re-running analysis-only (all cache hits) against the same 15 files and inspecting the raw candidate pool directly:
- 235 total candidates; `telemetry_pointed_down`/`subject_confidence` populated on all 235 (Layer 0/1 never silently no-op on real GoPro input).
- At the threshold used (`0.35`): **39/235 (16.6%) excluded.** At `0.2`: 17 excluded. At `0.5`: 55. At `0.7`: 170 (aggressive — most of the pool).
- Pulled thumbnails for the top-scoring excluded candidates and confirmed by eye: `GX013854.MP4` `[0.00-15.58s]` and `GX023854.MP4` `[97.85-155.37s]` are a sustained cluster of `telemetry_pointed_down≈0.96-1.0`, `subject_confidence=0.0` candidates — the actual frames are **solid black (camera in a pocket/bag)** and an **extreme motion-blurred close-up of an upside-down face** (camera dropped/being picked back up). Both are genuine, unambiguous "dead shot" content, correctly and confidently excluded.
- Pulled thumbnails for two of the lowest-scoring (most-confident-real-subject) candidates and confirmed by eye: both show a person carrying an infant car seat outdoors/in a car park — correctly kept.

**Layer 2 (Qwen) was not exercised live.** This test deployment of `um890` (`C:\BeatSyncTest\app\BeatSync-Engine-main`) has no llama.cpp binaries or Qwen GGUF weights installed (confirmed: `bin/llama-bin-win-vulkan-x64/` and `bin/models/*.gguf` are both absent), so `analyze_video_sources(..., enable_ai=...)` runs with `ai_available=False` and Layer 2 never fires. The schema/prompt changes were reviewed carefully against `_normalize_semantic()`'s validation and the `json_schema strict:true` request path (every `required` key, including the two new ones, must be present or the whole response is rejected — matches the existing pattern for `emotion`/`recommended_use`), but **installing the full Qwen/llama.cpp stack (multi-GB download) to live-test this one path was out of scope for this session** — flagging this explicitly per the "stop and flag it" precedent rather than asserting it works. If you want Layer 2 verified live, say so and I'll install the models and re-test.

## Known limitations (found during testing, not assumed)

1. **Chronic low-angle mount is invisible to Layer 0** by design (see "Notable decision"). A GoPro worn/mounted so it points somewhat down *for the entire clip* has no deviation event to detect.
2. **YOLOv8n can false-positive on extreme wide-angle/fisheye GoPro frames** at ~0.92 confidence (one confirmed instance in ~235 candidates). Layer 2 (Qwen), when installed, is the intended second opinion for exactly this case; it was not available to test here.
3. `min_subject_confidence` above ~0.6-0.7 starts excluding legitimate-but-jerky real footage (e.g. a fast handheld pan across a person) more often, since Layer 0's jerk signal doesn't distinguish "unstable subject shot" from "unstable dead shot" as reliably as the orientation signal does. The GUI's default (`0`, off) avoids this; I did not add an inline warning for high values because that's a UI-copy judgment call, not required by the spec.
4. If literally every candidate for a source fails the threshold, `filter_no_subject_candidates()` falls back to returning the **unfiltered** pool for that call rather than an empty list — this avoids the AV planner collapsing to naive/no-AI fallback sampling over one bad source, at the cost of occasionally allowing a dead shot through in a source that is *entirely* dead footage. Did not hit this case in testing (every source in the test folder had usable candidates).

## Syntax check

```
python3 -c "
import ast
for f in ['src/gopro_telemetry.py','src/subject_detection.py','src/video_analysis.py',
          'src/video_processor.py','src/gui.py','src/ui_content.py',
          'src/auto_mode/stage5_qwen_scene_worker.py','src/auto_mode/stage6_av_planner.py']:
    ast.parse(open(f).read()); print(f, 'OK')
"
```
All eight touched/added files parsed cleanly.

## Open items for the project owner

1. **Layer 2 live test** (see above) — say the word and I'll install the Qwen/llama.cpp stack on `um890` and re-verify `subject_visible`/`framing_issue` end to end.
2. `scripts/install.ps1`'s new `Install-YoloOnnxModel` step is unexercised (a full fresh install wasn't run this session) — worth a dry run before relying on it for a new machine.
3. Tune `min_subject_confidence`'s default UI value/step if `0.35` (used in testing) doesn't feel like the right "on" starting point once you try it yourself.
