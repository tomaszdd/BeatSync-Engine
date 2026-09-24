# Task: Fix subject detection for vertical crop — proper multi-box + baby-priority + GUI toggle

## Bug, confirmed from real plan data

`music_video_v8_vertical_ident_20260924_145852.plan.json` (the vertical-export verification
render) shows several clips with implausibly wide `subject_bbox` values — e.g. clip 4
(`GX013847.MP4`): `[0.221, 0.003, 0.989, 0.980]` (spans 77% of frame width), clip 20
(`GX013853.MP4`): `[0.443, 0.006, 0.998, 0.981]` (spans 56%). A single person almost never
legitimately occupies that much of a GoPro-close-range frame — this is almost certainly one
malformed box spanning multiple people (parent + baby together) rather than a clean detection of
either.

## Root cause (found by reading the code, not guessed)

`detect_subject()` in `src/subject_detection.py` (~line 108-138) does **not** run proper
multi-object detection. It takes the raw YOLOv8n output grid and picks **one single anchor** via
`np.argmax(person_scores)` — the single highest "person"-class-confidence anchor across the entire
prediction grid — with **no NMS (non-max suppression)** and **no enumeration of multiple
detections**. In a crowded/close scene (parent holding baby, both visible), the single
highest-scoring anchor's raw box regression can be poorly conditioned and produce one oversized box
that tries to span both people, instead of two separate clean boxes. There's also no logic anywhere
to distinguish "this detection is probably the baby" from "this detection is probably the adult" —
`detect_subject_bbox_for_clip()` (used by the vertical-crop feature from `VERTICAL_EXPORT_REPORT.md`)
just gets whatever single box this flawed detection returns.

## What to build

1. **Proper multi-detection with NMS**: rewrite `detect_subject()` (or add a new function used
   specifically by the vertical-crop path, keeping the existing single-box function for
   backward-compat with the quality-filter/subject-confidence Layer 1 use case if changing its
   return shape would ripple too far — your call, explain which approach you took and why) to
   enumerate ALL person-class detections above the confidence threshold across the prediction grid,
   apply standard NMS to collapse overlapping/duplicate anchor predictions into clean per-instance
   boxes, and return the resulting list of distinct person boxes (each with its own confidence and
   normalized bbox) rather than a single anchor's raw regression.
2. **Baby-priority selection heuristic** for the vertical-crop use case specifically: among the
   multiple clean person boxes NMS now returns, prefer the one most likely to be the baby rather
   than an adult. GoPro family footage of a newborn/infant means the baby is consistently much
   smaller in frame area than an adult and is usually held/carried (so its box often has a
   different aspect ratio than a standing/seated adult, and is frequently positioned in the lower-
   middle of frame near an adult's arms). A reasonable heuristic: among detected person boxes,
   prefer the smallest-area box that's still above a minimum plausible size (to avoid picking up
   noise/false-positive tiny detections) — but think through this carefully using the real
   detection data from this repo's actual footage (dump the raw NMS'd box list for a few of the
   problem clips above and eyeball which box is actually the baby vs the parent before hard-coding
   a threshold), and explain your chosen heuristic and its reasoning in the report, including any
   cases where it could plausibly still pick wrong.
3. **GUI toggle** (Create tab, `src/gui.py`, follow the existing `gr.Radio` pattern): a
   **"Vertical Crop Focus"** control with at least: `Auto (prefer smaller subject — baby/child)`
   (new default), `Auto (largest subject)` (the old single-detection behavior, kept as an option
   since Tomasz explicitly asked for a toggle, not just a silent behavior change), and `Center crop`
   (ignore subject detection entirely, geometric center — a safe fallback when detection gets a
   clip wrong and Tomasz wants to just force plain center framing for it). Wire through the same
   parameter-threading trail as `export_orientation`/`ident_outro_enabled` (settings persistence,
   `process_video()`, `create_music_video()`, `refine_rerender()`).
4. This only affects the **vertical export crop-positioning** path
   (`VERTICAL_EXPORT_REPORT.md`/`build_crop_to_fill_filter()` in `src/ffmpeg_processing.py`) — do
   not change how subject detection is used for the Layer 1 no-subject quality filter
   (`SUBJECT_DETECTION_REPORT.md`) unless you find the same single-anchor-no-NMS bug also causes a
   real problem there; if so, note it in your report but keep this task scoped to the vertical-crop
   use case as the primary deliverable.

## Verification (real hardware — required)

On `um890` (same setup as every prior task this session: venv python, app root, `D:\Photos\GoPro\
2025-10-01 Tereska Birth\`, 60s audio at `C:\BeatSyncTest\audio_60s.mp3`, warm cache, journey +
quality-filter + `min_subject_confidence=0.3`, transitions + title card enabled, export orientation
Vertical):

1. Re-render vertical mode with the new default (`Auto — prefer smaller subject`). Extract the same
   clips flagged above (`GX013847.MP4` around the problem timestamp, `GX013853.MP4` around its
   problem timestamp, and 2-3 others across the timeline) and visually compare crop framing
   before/after — confirm the baby is now reasonably in-frame where it previously might have been
   cut off or the crop was centered on an oversized/malformed box.
2. Dump the raw (pre- and post-fix) bbox data for these specific clips into the report so the
   before/after is verifiable from data, not just eyeballed screenshots.
3. Spot-check `Auto (largest subject)` and `Center crop` overrides both actually produce visibly
   different framing on at least one clip each, confirming the toggle genuinely works.
4. Confirm frame-accurate audio sync and genuine AMF hardware encode are unaffected (same checks as
   every prior verification this session).
5. Confirm the quality-filter / Layer 1 subject-confidence path (landscape renders, no vertical
   crop involved) is unaffected — spot-check one landscape render still behaves as before.

## Constraints

- Primarily touch `src/subject_detection.py`, `src/ffmpeg_processing.py`, `src/video_processor.py`,
  `src/gui.py`.
- No deletions outside the disposable `input/video_analysis_cache/` cache dir.
- Write findings to `BABY_FOCUSED_CROP_REPORT.md` in the repo root.
- **Commit AND push to `origin/main`, and paste real `git status`/`git log origin/main..HEAD`
  output — run AFTER pushing, not before — into the report as proof.**
