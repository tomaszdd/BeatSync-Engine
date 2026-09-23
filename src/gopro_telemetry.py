#!/usr/bin/env python3
"""GoPro GPMF telemetry pre-filter for Auto Mode candidate scoring (Layer 0).

Reads the GRAV/ACCL/GYRO streams GoPro embeds in the `gpmd` metadata track and
turns them into a cheap, no-frame-decode signal for "camera pointed at the
floor/sky" and "camera jostling in a pocket" -- computed once per source video
and looked up per candidate window by timestamp.

Parsing goes through the third-party `telemetry-parser` package (the Rust/PyO3
engine behind Gyroflow's camera-telemetry support) rather than a hand-rolled
GPMF/KLV reader, and specifically through its `normalized_imu()` API rather
than the raw per-model GPMF streams: normalized_imu() already corrects for the
axis-order/orientation differences that vary by GoPro model and firmware (see
SUBJECT_DETECTION_REPORT.md for the empirical verification against this
project's own footage). Non-GoPro sources (phone/camera footage) simply have
no gpmd track; that is treated as "no telemetry available", not an error.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

try:
    import telemetry_parser
except Exception:  # pragma: no cover - optional dependency
    telemetry_parser = None

BUCKET_SECONDS = 0.5

# A fixed axis convention ("Z is the lens/forward axis") turned out NOT to be
# reliable in practice: verified against this project's own GoPro footage
# (a chest-mounted HERO10, see SUBJECT_DETECTION_REPORT.md), gravity loaded
# the "forward" axis at ~0.93 during completely normal handheld filming for
# that mount -- a fixed forward-axis threshold would flag nearly the whole
# video. What generalizes is comparing each moment's gravity DIRECTION
# against this same video's own baseline direction (the mount's typical
# resting orientation, taken as the robust median direction across
# near-1g buckets): normal filming stays within ~15 deg of that baseline
# regardless of how the camera happens to be worn, while a genuine
# reorientation (pointed at the floor/ceiling, stuffed in a pocket) swings
# 40+ deg away from it. This also means the signal is blind to a mount that
# is *chronically* aimed low for the whole clip (there is no baseline
# deviation to detect) -- see the report's false-negative example.
_NEAR_G_LO = 0.75  # multiples of 9.81 m/s^2 -- excludes buckets with heavy
_NEAR_G_HI = 1.25  # dynamic acceleration that would corrupt the gravity read
_DEVIATION_DOT_LO = 0.906  # cos(25 deg): baseline noise band, not flagged
_DEVIATION_DOT_HI = 0.574  # cos(55 deg): fully flagged as reoriented

# Empirical jerk scale from this project's own GoPro footage: normal handheld
# motion/panning sits under ~2 deg/s^2 (gyro) and ~0.15 m/s^3 (accel) between
# 0.5s-bucket samples; pocket jostling spikes well past both.
_GYRO_JERK_SCALE = 6.0
_ACCL_JERK_SCALE = 0.35


def gopro_telemetry_available() -> bool:
    return telemetry_parser is not None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(lo, min(hi, value))


def extract_gopro_telemetry(video_file: str) -> Optional[Dict]:
    """Per-source-video GRAV/jerk summary, bucketed into fixed time windows.

    Returns None when telemetry-parser isn't installed, the source has no
    GPMF/gpmd track (regular phone/camera footage), or parsing otherwise
    fails for any reason -- callers must treat that as "no telemetry", the
    normal case for the large majority of sources, not a hard error.
    """
    if telemetry_parser is None:
        return None
    try:
        parser = telemetry_parser.Parser(video_file)
        imu = parser.normalized_imu()
    except Exception:
        return None
    if not imu:
        return None

    rows = []
    for sample in imu:
        try:
            accl = sample.get("accl")
            gyro = sample.get("gyro")
            if accl is None or gyro is None:
                continue
            t = float(sample.get("timestamp_ms", 0.0)) / 1000.0
            rows.append((t, float(accl[0]), float(accl[1]), float(accl[2]),
                         float(gyro[0]), float(gyro[1]), float(gyro[2])))
        except (TypeError, ValueError, IndexError):
            continue
    if len(rows) < 4:
        return None

    rows.sort(key=lambda row: row[0])
    times = np.asarray([row[0] for row in rows], dtype=float)
    accl = np.asarray([row[1:4] for row in rows], dtype=float)
    gyro = np.asarray([row[4:7] for row in rows], dtype=float)

    duration = float(times[-1])
    if duration <= 0:
        return None

    bucket_count = max(1, int(math.ceil(duration / BUCKET_SECONDS)))
    bucket_stats: List[Dict] = []
    for i in range(bucket_count):
        b_start = i * BUCKET_SECONDS
        b_end = min(duration, b_start + BUCKET_SECONDS)
        mask = (times >= b_start) & (times < b_end + 1e-6)
        if not np.any(mask):
            bucket_stats.append({"start": b_start, "end": b_end, "direction": None, "jerk": None})
            continue

        bucket_accl = accl[mask]
        bucket_gyro = gyro[mask]

        mean_accl = bucket_accl.mean(axis=0)
        magnitude = float(np.linalg.norm(mean_accl))
        direction = (mean_accl / magnitude, magnitude) if magnitude > 1e-6 else None

        if len(bucket_gyro) >= 2:
            gyro_jerk = float(np.mean(np.linalg.norm(np.diff(bucket_gyro, axis=0), axis=1)))
            accl_jerk = float(np.mean(np.linalg.norm(np.diff(bucket_accl, axis=0), axis=1)))
            jerk = _clamp(0.6 * (gyro_jerk / _GYRO_JERK_SCALE) + 0.4 * (accl_jerk / _ACCL_JERK_SCALE))
        else:
            jerk = None

        bucket_stats.append({"start": b_start, "end": b_end, "direction": direction, "jerk": jerk})

    # Robust baseline: this video's own typical resting orientation, taken as
    # the component-wise median direction across near-1g buckets (so a
    # minority of genuine floor/pocket buckets can't drag the baseline
    # toward themselves), renormalized to a unit vector.
    near_g = [
        b["direction"][0] for b in bucket_stats
        if b["direction"] is not None and _NEAR_G_LO <= b["direction"][1] / 9.81 <= _NEAR_G_HI
    ]
    if near_g:
        baseline = np.median(np.stack(near_g), axis=0)
        baseline_norm = float(np.linalg.norm(baseline))
        baseline = baseline / baseline_norm if baseline_norm > 1e-6 else None
    else:
        baseline = None

    buckets: List[Dict] = []
    for b in bucket_stats:
        pointed_down = None
        if baseline is not None and b["direction"] is not None:
            dot = float(np.dot(b["direction"][0], baseline))
            pointed_down = _clamp((_DEVIATION_DOT_LO - dot) / (_DEVIATION_DOT_LO - _DEVIATION_DOT_HI))
        buckets.append({
            "start": b["start"], "end": b["end"],
            "pointed_down": pointed_down, "jerk": b["jerk"],
        })

    return {"duration": duration, "buckets": buckets}


def telemetry_lookup(telemetry: Optional[Dict], start: float, end: float) -> Dict[str, Optional[float]]:
    """Average pointed-down confidence / jerk score over a candidate's [start, end)."""
    if not telemetry or not telemetry.get("buckets"):
        return {"telemetry_pointed_down": None, "telemetry_jerk_score": None}

    pointed_vals: List[float] = []
    jerk_vals: List[float] = []
    for bucket in telemetry["buckets"]:
        if bucket["end"] <= start or bucket["start"] >= end:
            continue
        if bucket["pointed_down"] is not None:
            pointed_vals.append(bucket["pointed_down"])
        if bucket["jerk"] is not None:
            jerk_vals.append(bucket["jerk"])

    return {
        "telemetry_pointed_down": float(np.mean(pointed_vals)) if pointed_vals else None,
        "telemetry_jerk_score": float(np.mean(jerk_vals)) if jerk_vals else None,
    }
