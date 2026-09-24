#!/usr/bin/env python3
"""UM890 data/visual verification for vertical crop focus modes."""

import json
import os
import sys

APP_DIR = r"C:\BeatSyncTest\app\BeatSync-Engine-main"
SRC_DIR = os.path.join(APP_DIR, "src")
for path in (APP_DIR, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from ffmpeg_processing import extract_clip_segment_ffmpeg
from subject_detection import (
    detect_subject,
    detect_subject_boxes,
    sample_frame_from_video,
    select_subject_bbox,
)
from ui_content import (
    VERTICAL_CROP_AUTO_LARGEST,
    VERTICAL_CROP_AUTO_SMALLER,
    VERTICAL_CROP_CENTER,
)


def rounded_bbox(bbox):
    return [round(float(value), 6) for value in bbox] if bbox else None


def main():
    footage = r"D:\Photos\GoPro\2025-10-01 Tereska Birth"
    output_dir = os.path.join(APP_DIR, "output", "baby_crop_modes")
    os.makedirs(output_dir, exist_ok=True)
    samples = [
        ("GX013843.MP4", 2.1),
        ("GX013847.MP4", 2.5),
        ("GX013849.MP4", 6.9),
        ("GX013853.MP4", 2.986286),
        ("GX013855.MP4", 7.4),
    ]
    results = []
    for name, timestamp in samples:
        source = os.path.join(footage, name)
        frame = sample_frame_from_video(source, timestamp)
        legacy_confidence, legacy_bbox = detect_subject(frame, min_confidence=0.05)
        detections = detect_subject_boxes(frame, min_confidence=0.05, only_person=True)
        row = {
            "source": name,
            "sample_timestamp": timestamp,
            "legacy_pre_nms": {
                "confidence": round(float(legacy_confidence), 6) if legacy_confidence is not None else None,
                "bbox": rounded_bbox(legacy_bbox),
            },
            "post_nms": [
                {"confidence": round(conf, 6), "bbox": rounded_bbox(bbox)}
                for conf, bbox in detections
            ],
            "selected_smaller": rounded_bbox(select_subject_bbox(detections, VERTICAL_CROP_AUTO_SMALLER)),
            "selected_largest": rounded_bbox(select_subject_bbox(detections, VERTICAL_CROP_AUTO_LARGEST)),
            "selected_center": None,
        }
        results.append(row)

    # The named GX013853 problem frame has multiple distinct detections, making
    # the three focus policies visibly different while holding source/time fixed.
    source = os.path.join(footage, "GX013853.MP4")
    start = 1.986286
    frame = sample_frame_from_video(source, start + 1.0)
    detections = detect_subject_boxes(frame, min_confidence=0.05, only_person=True)
    for label, mode in (
        ("smaller", VERTICAL_CROP_AUTO_SMALLER),
        ("largest", VERTICAL_CROP_AUTO_LARGEST),
        ("center", VERTICAL_CROP_CENTER),
    ):
        bbox = select_subject_bbox(detections, mode)
        output = os.path.join(output_dir, f"GX013853_{label}.mp4")
        ok = extract_clip_segment_ffmpeg(
            source, start, 2.0, output, 30.0, (1080, 1920), True,
            gpu_encoder="h264_amf", subject_bbox=bbox,
        )
        if not ok:
            raise RuntimeError(f"Could not render {mode} override")

    output_json = os.path.join(output_dir, "verification.json")
    with open(output_json, "w", encoding="utf-8") as handle:
        json.dump({"samples": results}, handle, indent=2)
    print(json.dumps({"output": output_json, "samples": results}, indent=2))


if __name__ == "__main__":
    main()
