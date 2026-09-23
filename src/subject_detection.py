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
from typing import Optional, Sequence

import numpy as np

from logger import ROOT_DIR

DEFAULT_ONNX_PATH = os.path.join(ROOT_DIR, "bin", "models", "yolov8n.onnx")
INPUT_SIZE = 320
CONFIDENCE_THRESHOLD = 0.15

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
