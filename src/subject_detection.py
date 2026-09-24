#!/usr/bin/env python3
"""YOLOv8n subject pre-filter for Auto Mode candidate scoring (Layer 1).

Runs a small local object detector (YOLOv8n, a few MB, CPU-fast, no GPU
required) against a sample frame already decoded for the deterministic
sharpness/motion/quality metrics in video_analysis.py -- no extra frame
reads. Produces a subject_confidence (0..1): does the sampled frame contain a
person or other clear foreground subject, vs. blank floor/ceiling/pocket
darkness.

Runs through onnxruntime against a pre-exported yolov8n.onnx rather than the
`ultralytics` PyPI package: this repo deliberately migrated its AI stack off
PyTorch/Transformers onto llama.cpp/Vulkan (see scripts/install.ps1's
Remove-LegacyPythonPackages and its "legacy packages" install-verification
gate) to avoid the multi-GB PyTorch/CUDA install; `ultralytics` hard-depends
on torch even for CPU inference, so pulling it in would silently reintroduce
exactly what that migration removed. onnxruntime has no such dependency.
bin/models/yolov8n.onnx is produced with a one-time `ultralytics` export
(`YOLO('yolov8n.pt').export(format='onnx', imgsz=320)`) that never needs to
run again on the target machine -- see SUBJECT_DETECTION_REPORT.md.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from logger import ROOT_DIR

DEFAULT_ONNX_PATH = os.path.join(ROOT_DIR, "bin", "models", "yolov8n.onnx")
INPUT_SIZE = 320
CONFIDENCE_THRESHOLD = 0.15

# Quality filter thresholds (deterministic Layer 1 quality pre-filter).
# Darkness: mean pixel luminance below 5% (mean pixel value < ~12.8 / 255) indicates a near-black
# frame (camera in pocket, obstructed lens, or bad exposure moment).
DEFAULT_MIN_LUMINANCE = 0.05

# Blur: variance of Laplacian on max-360px downscaled frames below this threshold indicates severe
# motion blur smear (e.g. camera whip-pans past lights, dropped camera) where subjects are unrecognizable.
# Conservative: fast handheld pans across a real person maintain var >= 400 (see SUBJECT_DETECTION_REPORT.md).
DEFAULT_MIN_LAPLACIAN_VAR = 65.0

# Standard COCO class order (index == YOLOv8's class id). Only the indices
# this project treats as "a subject is in frame" are named here -- people are
# the primary target (this pipeline mostly runs on family/event footage),
# plus a handful of common foreground subjects so an establishing shot of a
# pet or a car isn't penalized the same way a blank floor/ceiling shot is.
_SUBJECT_CLASS_IDS = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    14: "bird", 15: "cat", 16: "dog", 17: "horse",
}

_session = None
_input_name: Optional[str] = None
_session_lock = threading.Lock()
_load_failed = False


def subject_detection_available() -> bool:
    return _load_session() is not None


def _load_session():
    global _session, _input_name, _load_failed
    if _session is not None or _load_failed:
        return _session
    with _session_lock:
        if _session is not None or _load_failed:
            return _session
        if os.environ.get("BEATSYNC_SUBJECT_DETECTION", "1") == "0":
            _load_failed = True
            return None
        onnx_path = os.environ.get("BEATSYNC_YOLO_ONNX_PATH", DEFAULT_ONNX_PATH)
        if not os.path.exists(onnx_path):
            print(f"   Warning: subject detector model not found: {onnx_path}")
            _load_failed = True
            return None
        try:
            import onnxruntime as ort
            session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
            _input_name = session.get_inputs()[0].name
            _session = session
        except Exception as e:
            print(f"   Warning: subject detector (YOLOv8n ONNX) unavailable: {e}")
            _load_failed = True
            _session = None
    return _session


def _letterbox(frame: np.ndarray, size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = size / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    import cv2
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
    return chw[None, ...]


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.45) -> List[int]:
    """Non-maximum suppression for bounding boxes in normalized coordinates."""
    if len(boxes) == 0:
        return []
    x0, y0, x1, y1 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x1 - x0) * (y1 - y0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx0 = np.maximum(x0[i], x0[order[1:]])
        yy0 = np.maximum(y0[i], y0[order[1:]])
        xx1 = np.minimum(x1[i], x1[order[1:]])
        yy1 = np.minimum(y1[i], y1[order[1:]])
        w = np.maximum(0.0, xx1 - xx0)
        h = np.maximum(0.0, yy1 - yy0)
        inter = w * h
        union = areas[i] + areas[order[1:]] - inter
        iou = inter / np.maximum(union, 1e-6)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]
    return keep


def detect_subject_boxes(
    frame: np.ndarray,
    min_confidence: float = 0.05,
    iou_threshold: float = 0.45,
    only_person: bool = True,
) -> List[Tuple[float, Tuple[float, float, float, float]]]:
    """Detect person (or subject) bounding boxes in a BGR frame using YOLOv8n with NMS.

    Returns a list of (confidence, (x0, y0, x1, y1)) sorted by confidence descending,
    where coordinates are normalized to [0..1].
    """
    session = _load_session()
    if session is None or frame is None or getattr(frame, 'size', 0) == 0:
        return []

    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return []

    scale = INPUT_SIZE / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    top, left = (INPUT_SIZE - nh) // 2, (INPUT_SIZE - nw) // 2

    try:
        input_tensor = _letterbox(frame, INPUT_SIZE)
        outputs = session.run(None, {_input_name: input_tensor})
        pred = outputs[0][0]  # (4 + 80, num_anchors)
        class_scores = pred[4:, :]
        person_scores = class_scores[0, :]

        mask = person_scores >= min_confidence
        anchors = np.where(mask)[0]

        target_scores = person_scores
        # If no person detected and not strictly only_person, check other subject classes
        if len(anchors) == 0 and not only_person:
            target_rows = sorted(_SUBJECT_CLASS_IDS.keys())
            subject_scores = class_scores[target_rows, :]
            if subject_scores.size:
                max_pos = np.unravel_index(np.argmax(subject_scores), subject_scores.shape)
                if float(subject_scores[max_pos]) >= min_confidence:
                    row_idx = target_rows[max_pos[0]]
                    target_scores = class_scores[row_idx, :]
                    anchors = np.where(target_scores >= min_confidence)[0]

        if len(anchors) == 0:
            return []

        boxes = []
        scores = []
        for idx in anchors:
            s = float(target_scores[idx])
            cx, cy, bw, bh = pred[:4, idx]
            x0_c = cx - bw / 2.0
            x1_c = cx + bw / 2.0
            y0_c = cy - bh / 2.0
            y1_c = cy + bh / 2.0
            x0 = max(0.0, min(1.0, (x0_c - left) / float(nw)))
            x1 = max(0.0, min(1.0, (x1_c - left) / float(nw)))
            y0 = max(0.0, min(1.0, (y0_c - top) / float(nh)))
            y1 = max(0.0, min(1.0, (y1_c - top) / float(nh)))
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0

            bw_ = x1 - x0
            bh_ = y1 - y0
            if bw_ >= 0.03 and bh_ >= 0.03:
                ar = bh_ / bw_
                if 0.20 <= ar <= 5.0:
                    boxes.append([x0, y0, x1, y1])
                    scores.append(s)

        if not boxes:
            return []

        kept = nms(np.array(boxes), np.array(scores), iou_threshold=iou_threshold)
        return [(float(scores[k]), (float(boxes[k][0]), float(boxes[k][1]), float(boxes[k][2]), float(boxes[k][3]))) for k in kept]

    except Exception as e:
        print(f"   Warning: subject detection inference failed: {e}")
        return []


def select_subject_bbox(
    detections: Sequence[Tuple[float, Tuple[float, float, float, float]]],
    focus_mode: str = "Auto (prefer smaller subject — baby/child)",
    min_baby_area: float = 0.012,
    max_baby_area: float = 0.35,
) -> Optional[Tuple[float, float, float, float]]:
    """Select the best subject bounding box given multi-person detections and focus mode.

    focus_mode options:
      - 'Auto (prefer smaller subject — baby/child)': prioritizes infants/children (default)
      - 'Auto (largest subject)': prioritizes largest person (legacy behavior)
      - 'Center crop': returns None (geometric center crop)
    """
    if not detections:
        return None

    if "center" in focus_mode.lower():
        return None

    if "largest" in focus_mode.lower():
        # Largest subject by area; tie-break by confidence
        best = max(detections, key=lambda d: ((d[1][2] - d[1][0]) * (d[1][3] - d[1][1]), d[0]))
        return best[1]

    # Baby-priority selection heuristic
    # Filter out edge artifacts (truncated thin boxes at extreme borders)
    valid_cands = []
    for conf, bbox in detections:
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        area = bw * bh
        is_edge_sliver = (bbox[0] < 0.005 or bbox[2] > 0.995) and bw < 0.12
        if area >= min_baby_area and not is_edge_sliver:
            valid_cands.append((conf, bbox, area))

    if not valid_cands:
        # Fall back to highest confidence detection
        return detections[0][1]

    if len(valid_cands) == 1:
        return valid_cands[0][1]

    # Multiple candidates: check for baby/child-sized candidates
    baby_cands = [c for c in valid_cands if c[2] <= max_baby_area]
    if baby_cands:
        # Among baby-sized candidates, prefer ones positioned plausibly in frame (y1 > 0.30)
        plausible_babies = [c for c in baby_cands if c[1][3] > 0.30]
        candidates_to_rank = plausible_babies if plausible_babies else baby_cands
        # Prefer the smallest area candidate in the baby range
        best_baby = min(candidates_to_rank, key=lambda c: c[2])
        return best_baby[1]

    # If all candidates exceed max_baby_area (all adults), pick the smallest among them
    best = min(valid_cands, key=lambda c: c[2])
    return best[1]


def detect_subject(
    frame: np.ndarray,
    min_confidence: float = CONFIDENCE_THRESHOLD,
) -> Tuple[Optional[float], Optional[Tuple[float, float, float, float]]]:
    """Detect the legacy primary subject used by the Layer 1 quality filter.

    Preserves backward compatibility with Layer 1 quality filter / subject scoring.
    Returns (confidence, bbox) where bbox is normalized (x0, y0, x1, y1) in [0..1].
    Returns (None, None) if the model is unavailable or frame is invalid.
    Returns (conf, None) if no subject meets min_confidence.
    """
    session = _load_session()
    if session is None or frame is None or getattr(frame, 'size', 0) == 0:
        return None, None
    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return None, None

    scale = INPUT_SIZE / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    top, left = (INPUT_SIZE - nh) // 2, (INPUT_SIZE - nw) // 2

    try:
        pred = session.run(None, {_input_name: _letterbox(frame, INPUT_SIZE)})[0][0]
        class_scores = pred[4:, :]
        target_rows = sorted(_SUBJECT_CLASS_IDS.keys())
        person_scores = class_scores[0, :]
        max_person_score = float(person_scores.max()) if person_scores.size else 0.0
        if max_person_score >= min_confidence:
            best_score = max_person_score
            anchor_idx = int(np.argmax(person_scores))
        else:
            subject_scores = class_scores[target_rows, :]
            if not subject_scores.size:
                return 0.0, None
            max_pos = np.unravel_index(np.argmax(subject_scores), subject_scores.shape)
            best_score = float(subject_scores[max_pos])
            anchor_idx = int(max_pos[1])
        if best_score < min_confidence:
            return float(max(0.0, best_score)), None

        cx, cy, bw, bh = pred[:4, anchor_idx]
        x0 = max(0.0, min(1.0, (cx - bw / 2.0 - left) / float(nw)))
        x1 = max(0.0, min(1.0, (cx + bw / 2.0 - left) / float(nw)))
        y0 = max(0.0, min(1.0, (cy - bh / 2.0 - top) / float(nh)))
        y1 = max(0.0, min(1.0, (cy + bh / 2.0 - top) / float(nh)))
        return float(max(0.0, min(1.0, best_score))), (
            float(min(x0, x1)), float(min(y0, y1)),
            float(max(x0, x1)), float(max(y0, y1)),
        )
    except Exception as e:
        print(f"   Warning: subject detection inference failed: {e}")
        return None, None


def detect_subject_bbox(
    frame: np.ndarray,
    min_confidence: float = 0.20,
) -> Optional[Tuple[float, float, float, float]]:
    """Legacy convenience helper retained for Layer 1 compatibility."""
    _, bbox = detect_subject(frame, min_confidence=min_confidence)
    return bbox


def score_subject_and_bbox(
    frames: Sequence[np.ndarray],
    min_confidence: float = CONFIDENCE_THRESHOLD,
) -> Tuple[Optional[float], Optional[Tuple[float, float, float, float]]]:
    """Best subject detection score and corresponding bbox across frames."""
    frames = [f for f in frames if f is not None]
    if not frames:
        return None, None

    best_score: Optional[float] = None
    best_bbox: Optional[Tuple[float, float, float, float]] = None

    for f in frames:
        score, bbox = detect_subject(f, min_confidence=min_confidence)
        if score is not None:
            if best_score is None or score > best_score:
                best_score = score
                best_bbox = bbox

    return best_score, best_bbox


def score_subject_confidence(frames: Sequence[np.ndarray]) -> Optional[float]:
    """Max person/subject detection confidence across the given BGR frames.

    Returns None (not 0.0) when the detector isn't available, so callers can
    tell "no subject detected" apart from "couldn't check" and stay lenient
    in the latter case.
    """
    score, _ = score_subject_and_bbox(frames, min_confidence=CONFIDENCE_THRESHOLD)
    return score


def sample_frame_from_video(video_file: str, timestamp: float = 0.0) -> Optional[np.ndarray]:
    """Extract a single BGR frame from a video or image file."""
    if not video_file or not os.path.isfile(video_file):
        return None
    ext = os.path.splitext(video_file)[1].lower()
    if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.heic', '.heif'):
        try:
            import cv2
            return cv2.imread(video_file)
        except Exception:
            return None
    try:
        import cv2
        cap = cv2.VideoCapture(video_file)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(timestamp) * 1000.0))
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None and frame.size > 0:
            return frame
    except Exception:
        pass
    return None


def detect_subject_bbox_for_clip(
    video_file: str,
    start_time: float,
    duration: float,
    min_confidence: float = 0.05,
    focus_mode: str = "Auto (prefer smaller subject — baby/child)",
) -> Optional[Tuple[float, float, float, float]]:
    """Detect subject bbox for a video clip by sampling a frame from the clip window."""
    if "center" in focus_mode.lower():
        return None
    sample_time = start_time + min(max(0.1, duration), 2.0) * 0.5
    frame = sample_frame_from_video(video_file, sample_time)
    if frame is None and start_time > 0:
        frame = sample_frame_from_video(video_file, start_time)
    if frame is None:
        return None
    dets = detect_subject_boxes(frame, min_confidence=min_confidence, only_person=True)
    if not dets:
        dets = detect_subject_boxes(frame, min_confidence=min_confidence, only_person=False)
    return select_subject_bbox(dets, focus_mode=focus_mode)



def score_frame_darkness(frames: Sequence[np.ndarray]) -> Dict[str, float]:
    """Computes deterministic luminance metrics across decoded BGR frames.

    Returns dict with:
      - min_luminance: minimum mean pixel luminance across frames (0..1)
      - mean_luminance: average mean pixel luminance across frames (0..1)
    """
    frames = [f for f in frames if f is not None]
    if not frames:
        return {"min_luminance": 0.0, "mean_luminance": 0.0}

    import cv2
    lums = []
    for f in frames:
        h, w = f.shape[:2]
        if w > 360:
            scale = 360 / float(w)
            small = cv2.resize(f, (360, max(2, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        else:
            small = f
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        lums.append(float(np.mean(gray) / 255.0))

    return {
        "min_luminance": float(np.min(lums)),
        "mean_luminance": float(np.mean(lums)),
    }


def score_frame_blur(frames: Sequence[np.ndarray]) -> Dict[str, float]:
    """Computes deterministic Laplacian sharpness metrics across decoded BGR frames.

    Returns dict with:
      - min_laplacian: minimum variance of Laplacian across frames
      - mean_laplacian: average variance of Laplacian across frames
    """
    frames = [f for f in frames if f is not None]
    if not frames:
        return {"min_laplacian": 0.0, "mean_laplacian": 0.0}

    import cv2
    laps = []
    for f in frames:
        h, w = f.shape[:2]
        if w > 360:
            scale = 360 / float(w)
            small = cv2.resize(f, (360, max(2, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        else:
            small = f
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        laps.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

    return {
        "min_laplacian": float(np.min(laps)),
        "mean_laplacian": float(np.mean(laps)),
    }


def score_frame_quality(frames: Sequence[np.ndarray]) -> Dict[str, float]:
    """Computes combined deterministic darkness and sharpness metrics across decoded BGR frames."""
    darkness = score_frame_darkness(frames)
    blur = score_frame_blur(frames)
    return {**darkness, **blur}


def is_unusable_quality(
    candidate: Dict[str, Any],
    min_luminance: float = DEFAULT_MIN_LUMINANCE,
    min_laplacian: float = DEFAULT_MIN_LAPLACIAN_VAR,
) -> Tuple[bool, Optional[str]]:
    """Determine whether a candidate is unusable due to darkness or severe motion blur.

    Returns (is_unusable, reason) where reason is 'darkness' or 'motion_blur' or None.
    Evaluates deterministically without LLM, checking candidate quality fields
    with fallback to legacy candidate fields (e.g. brightness, telemetry).
    """
    # 1. Darkness check: near-total black frame (camera in pocket, obstructed, bad exposure)
    mean_lum = candidate.get("mean_luminance")
    if mean_lum is None:
        mean_lum = candidate.get("brightness")
    min_lum = candidate.get("min_luminance")

    if mean_lum is not None and float(mean_lum) < min_luminance:
        return True, "darkness"
    if min_lum is not None and float(min_lum) < 0.03 and (mean_lum is None or float(mean_lum) < 0.08):
        return True, "darkness"

    # 2. Blur check: severe motion blur smear (e.g. whip-pan past ceiling light)
    min_lap = candidate.get("min_laplacian")
    mean_lap = candidate.get("mean_laplacian")
    if min_lap is not None and float(min_lap) < min_laplacian:
        return True, "motion_blur"
    if mean_lap is not None and float(mean_lap) < min_laplacian:
        return True, "motion_blur"

    # Telemetry/motion fallback for legacy cached candidates lacking min_laplacian:
    # A whip-pan / drop event swings 40+ degrees from baseline and has high jerk and motion
    pointed_down = candidate.get("telemetry_pointed_down")
    jerk = candidate.get("telemetry_jerk_score")
    motion = candidate.get("motion", 0.0)
    if pointed_down is not None and jerk is not None:
        if float(pointed_down) > 0.85 and float(jerk) > 0.60 and float(motion) > 0.40:
            return True, "motion_blur"

    return False, None
