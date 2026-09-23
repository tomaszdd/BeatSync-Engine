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
from typing import Any, Dict, Optional, Sequence, Tuple

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


def score_subject_confidence(frames: Sequence[np.ndarray]) -> Optional[float]:
    """Max person/subject detection confidence across the given BGR frames.

    Returns None (not 0.0) when the detector isn't available, so callers can
    tell "no subject detected" apart from "couldn't check" and stay lenient
    in the latter case.
    """
    session = _load_session()
    frames = [f for f in frames if f is not None]
    if session is None or not frames:
        return None

    best = 0.0
    target_rows = sorted(_SUBJECT_CLASS_IDS.keys())
    try:
        for frame in frames:
            input_tensor = _letterbox(frame, INPUT_SIZE)
            outputs = session.run(None, {_input_name: input_tensor})
            # YOLOv8 ONNX export output: (1, 4 + num_classes, num_anchors).
            pred = outputs[0][0]
            class_scores = pred[4:, :]
            subject_scores = class_scores[target_rows, :]
            if subject_scores.size:
                best = max(best, float(subject_scores.max()))
    except Exception as e:
        print(f"   Warning: subject detection inference failed: {e}")
        return None

    if best < CONFIDENCE_THRESHOLD:
        return 0.0
    return max(0.0, min(1.0, best))


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
