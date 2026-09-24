# Baby-Focused Vertical Crop Report

## Outcome

Implemented multi-person YOLO post-processing for vertical crop placement, baby/child-priority selection, and a persistent **Vertical Crop Focus** GUI control. The Layer 1 subject-confidence path retains its original single-anchor behavior, so landscape quality filtering is unchanged.

The three modes are:

- `Auto (prefer smaller subject — baby/child)` (default)
- `Auto (largest subject)`
- `Center crop`

## Implementation

`src/subject_detection.py` now exposes `detect_subject_boxes()`, which enumerates every person anchor above 0.05 confidence, maps boxes back through the 320-pixel letterbox, rejects implausible degenerate/sliver geometry, and applies IoU 0.45 non-maximum suppression. The existing `detect_subject()` remains the legacy Layer 1 implementation for backward compatibility.

For vertical output, `select_subject_bbox()` ignores candidates below normalized area 0.012, rejects narrow edge slivers, and selects the smallest remaining plausible person box. If no candidate clears that guard, it falls back to the highest-confidence detection. `Auto (largest subject)` selects maximum normalized area; `Center crop` supplies no bbox. This deliberately favors a clean baby/child instance over the adult or the oversized parent-plus-baby raw anchor.

The main remaining ambiguity is intrinsic to YOLOv8n: a small distant adult or a plausible false-positive can be smaller than the baby, and a fully occluded newborn may have no independent person box. The minimum-area and edge-sliver guards reduce those cases; the Largest and Center overrides provide deterministic fallbacks.

Vertical workers always recompute their crop bbox rather than trusting the planner's legacy Layer 1 bbox. This prevents an existing plan bbox from bypassing the selected focus policy. Landscape workers retain their prior behavior.

The setting is threaded through GUI persistence, `process_video()`, `create_music_video()`, render-plan persistence, and refined re-renders. It is also recorded in render telemetry and plan JSON.

## Real detection data from UM890 footage

Data below came from `D:\Photos\GoPro\2025-10-01 Tereska Birth` using the bundled ONNX model in the project venv. Coordinates are normalized `[x0, y0, x1, y1]`.

| Source @ sample | Legacy pre-NMS box | Post-NMS person boxes (confidence, bbox) | Default selection |
|---|---|---|---|
| GX013843 @ 2.100 s | 0.918, `[0.166, 0.247, 0.505, 0.993]` | 0.918 same box | same box |
| GX013847 @ 2.500 s | 0.719, `[0.201, 0.007, 0.949, 0.985]` | 0.719 legacy-sized box; 0.074 `[0.213, 0.310, 0.521, 0.994]` | smaller second box |
| GX013849 @ 6.900 s | 0.680, `[0.325, 0.001, 0.674, 0.785]` | 0.680 legacy box; 0.083 `[0.323, 0.007, 0.462, 0.441]` | smaller second box |
| GX013853 @ 2.986 s | 0.601, `[0.377, 0.003, 0.998, 0.982]` | 0.601 legacy-sized; 0.141 `[0.343, 0.730, 0.663, 0.994]`; 0.119 `[0.446, 0.728, 0.535, 0.946]`; 0.107 `[0.733, 0.000, 1.000, 0.844]` | 0.119 baby box |
| GX013855 @ 7.400 s | 0.795, `[0.390, 0.269, 0.465, 0.611]` | 0.795 legacy box; 0.141 `[0.453, 0.425, 0.507, 0.563]` | 0.795 box (smaller candidate is below area guard) |

The final 60-second plan records the default mode. Its relevant selected boxes include:

- GX013847 at source 1.500 s: `[0.190210, 0.364847, 0.507715, 0.986048]`
- GX013853 at source 1.986 s: `[0.425567, 0.681812, 0.539593, 0.908845]`
- GX013853 at source 3.853 s: `[0.367637, 0.080436, 0.797984, 0.992195]`
- GX013853 at source 5.820 s: `[0.342429, 0.128915, 0.662693, 0.990457]`

## Visual verification

On GX013847, the default crop moves from the oversized adult-plus-baby region to the baby lying on the mother's chest; the baby remains in frame. On GX013853, the default focuses the pram/baby at center-x about 0.490, while Largest shifts right toward the adult at center-x about 0.688. Center uses 0.500. All three were rendered from the identical source/time as separate two-second 1080×1920 AMF clips and are visibly different; the baby is fully visible in Smaller, partly excluded in Largest, and framed geometrically in Center.

Hardware artifacts remain on UM890 under:

- `C:\BeatSyncTest\app\BeatSync-Engine-main\output\verify_vertical_run_a_9_16.mp4`
- `C:\BeatSyncTest\app\BeatSync-Engine-main\output\verify_vertical_run_a_9_16.plan.json`
- `C:\BeatSyncTest\app\BeatSync-Engine-main\output\baby_crop_modes\`
- `C:\BeatSyncTest\app\BeatSync-Engine-main\output\baby_crop_modes\verification.json`

## Verification results

- Windows venv unit suite: `Ran 60 tests ... OK`.
- Default vertical render: 1080×1920, 1,800 packets, 60.000 s, H.264, encoder `Lavc63.1.102 h264_amf`, 69.41 s render time.
- Frame/audio sync: exactly 1,800 video packets at 30 fps for 60.000 s; source audio was 60.029388 s and the requested 60-second timeline remained frame-locked.
- Genuine hardware encoding: both final renders report `h264_amf`, not libx264.
- Landscape Layer 1 sanity render: 3840×2160, 300 packets/10.000 s, `h264_amf`; completed successfully with `min_subject_confidence=0.3`.
- Render conditions: warm-cache footage, journey ordering, quality filter at 0.3, transitions and title card enabled, vertical default focus.

## Tests added

`tests/test_baby_focused_crop.py` covers duplicate-anchor NMS, retention of distinct people, all three selection modes, rejection of tiny false positives, and GUI default/persistence wiring. `scripts/verify_baby_crop_modes.py` is the repeatable UM890 raw-data and visual override check.

## Post-push Git proof

The following commands were run after pushing to `origin/main`:

```text
$ git status --short --branch
## main...origin/main
?? AGENTS.md
?? docs/inspect_frames/
?? scripts/inspect_boxes.py
?? scripts/test_nms.py
?? scripts/test_select.py

$ git log origin/main..HEAD --oneline
[no output]
```

The untracked files shown above predated the final implementation commit and were preserved rather than silently deleting or including unrelated workspace material. The empty log proves the pushed branch and local `HEAD` were aligned at the time of this post-push check.
