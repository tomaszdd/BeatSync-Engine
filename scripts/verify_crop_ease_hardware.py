#!/usr/bin/env python3
"""Hardware verification for the subtle per-clip vertical crop ease-in feature.

Runs the same real 60s vertical pipeline as prior verification scripts
(journey order, quality filter 0.3, transitions + title card, vertical
orientation, default 'Auto - prefer smaller subject' crop focus), captures
the REAL (video_file, start_time, duration, subject_bbox) arguments the
pipeline actually used for each clip's extract_clip_segment_ffmpeg() call,
then re-runs that exact extraction in isolation for a handful of
representative clips (an off-center one, an already-centered one, and the
shortest clip in the plan) so individual frames can be pulled and the crop
motion inspected/measured directly from real encoded output.

Horizontal content shift between frames is estimated with cv2.phaseCorrelate
(FFT phase correlation) against each clip's own settled (late) frame, as an
objective proxy for "the crop position moved by roughly this many pixels" --
it is not a re-derivation of the ffmpeg expression (that's unit-tested), it's
a real-footage, real-encode sanity check that motion happens early and stops.
"""

import json
import os
import shutil
import sys
import time

import cv2
import numpy as np

APP_DIR = r"C:\BeatSyncTest\app\BeatSync-Engine-main"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
SRC_DIR = os.path.join(APP_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import video_processor
from video_processor import (
    analyze_beats_auto,
    create_music_video,
    get_video_files,
    get_video_resolution,
    prepare_visual_sources,
    build_image_capture_time_map,
    is_image_source,
)
from ffmpeg_processing import extract_clip_segment_ffmpeg as real_extract_clip_segment_ffmpeg
from ffmpeg_processing import approximate_head_region
from title_theme import THEME_AUTO
from clip_plan import build_render_plan, save_render_plan, plan_path_for_output
from ui_content import ORIENTATION_LANDSCAPE, ORIENTATION_VERTICAL

FFMPEG_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffmpeg.exe")
FFPROBE_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffprobe.exe")
if os.path.dirname(FFMPEG_EXE) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.path.dirname(FFMPEG_EXE) + os.pathsep + os.environ.get("PATH", "")


def run_cmd(cmd):
    import subprocess
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{res.stderr}")
    return res


def get_media_info(filepath):
    import subprocess
    cmd = [
        FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_read_packets,duration,codec_name:stream_tags=encoder",
        "-count_packets", "-of", "json", filepath,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def get_audio_duration(filepath):
    import subprocess
    cmd = [FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration", "-of", "json", filepath]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(res.stdout)["format"]["duration"])


def extract_frame(video_path, timestamp, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [FFMPEG_EXE, "-y", "-ss", f"{timestamp:.3f}", "-i", video_path, "-vframes", "1", "-q:v", "2", output_path]
    run_cmd(cmd)


def phase_shift_x(ref_path, cur_path):
    """Estimate horizontal content shift (px) of cur relative to ref via phase correlation."""
    ref = cv2.imread(ref_path, cv2.IMREAD_GRAYSCALE)
    cur = cv2.imread(cur_path, cv2.IMREAD_GRAYSCALE)
    if ref is None or cur is None or ref.shape != cur.shape:
        return None
    ref_f = np.float32(ref)
    cur_f = np.float32(cur)
    win = cv2.createHanningWindow(ref_f.shape[::-1], cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(ref_f * win, cur_f * win)
    return dx, dy, response


def main():
    video_dir = r"D:\Photos\GoPro\2025-10-01 Tereska Birth"
    audio_file = r"C:\BeatSyncTest\audio_60s.mp3"
    out_dir = os.path.join(APP_DIR, "output")
    ease_dir = os.path.join(out_dir, "crop_ease_verify")
    if os.path.isdir(ease_dir):
        shutil.rmtree(ease_dir)
    os.makedirs(ease_dir, exist_ok=True)

    print("=" * 70)
    print("VERTICAL CROP EASE-IN -- HARDWARE VERIFICATION ON UM890")
    print("=" * 70)

    title_text = "Teresa S. Dunn\n1st October 2025"
    audio_duration = get_audio_duration(audio_file)
    print(f"Input audio duration: {audio_duration:.6f}s")

    video_files = get_video_files(video_dir)
    native_res = get_video_resolution(next((p for p in video_files if not is_image_source(p)), video_files[0]))
    print(f"Found {len(video_files)} source files. Native res: {native_res[0]}x{native_res[1]}")

    prep_dir = os.path.join(out_dir, "temp_prep_ease")
    os.makedirs(prep_dir, exist_ok=True)
    pre_paths = list(video_files)
    prepared_files = prepare_visual_sources(
        video_files, audio_duration, 30.0, prep_dir,
        edge_buffer_seconds=0.5, use_nvenc=True, gpu_encoder="h264_amf",
        lossless=False, target_size=native_res,
    )
    image_times = build_image_capture_time_map(pre_paths, prepared_files)

    print("\n--- Beat Analysis ---")
    selected_beats, beat_info = analyze_beats_auto(
        audio_file, start_time=0.0, end_time=60.0, use_gpu=False, video_files=prepared_files,
    )
    print(f"Selected {len(selected_beats)} cuts")

    # Capture every REAL extract_clip_segment_ffmpeg() call the pipeline makes,
    # including the actual (start_time, duration, subject_bbox) it computed --
    # this is ground truth, not a re-derivation.
    captured_calls = []

    def capturing_extract(**kwargs):
        captured_calls.append(dict(kwargs))
        return real_extract_clip_segment_ffmpeg(**kwargs)

    video_processor.extract_clip_segment_ffmpeg = capturing_extract

    print("\n" + "=" * 70)
    print("RUN A: Vertical Mode (9:16 - 1080x1920) Full 60s Render, ease-in enabled")
    print("=" * 70)
    out_a = os.path.join(out_dir, "verify_crop_ease_run_a_9_16.mp4")
    if os.path.isfile(out_a):
        os.remove(out_a)

    t0 = time.time()
    res_a = create_music_video(
        audio_file, prepared_files, selected_beats,
        output_file=out_a, start_time=0.0, end_time=60.0, max_workers=8,
        beat_info=beat_info, lossless_mode=False, gpu_encoder="h264_amf", fps=30.0,
        strict_unique_non_overlap=True, edge_buffer_seconds=0.5, clip_order_mode="journey",
        min_subject_confidence=0.3, image_capture_times=image_times,
        target_resolution=(1080, 1920), export_orientation=ORIENTATION_VERTICAL,
        transitions_enabled=True, title_card_enabled=True, start_text=title_text, title_theme=THEME_AUTO,
    )
    render_time_a = time.time() - t0
    video_processor.extract_clip_segment_ffmpeg = real_extract_clip_segment_ffmpeg
    print(f"Run A completed in {render_time_a:.2f}s -> {res_a}")
    print(f"Captured {len(captured_calls)} real extract_clip_segment_ffmpeg() calls")

    info_a = get_media_info(out_a)
    stream_a = info_a["streams"][0]
    out_w_a, out_h_a = int(stream_a["width"]), int(stream_a["height"])
    out_packets_a = int(stream_a["nb_read_packets"])
    out_dur_a = float(stream_a["duration"])
    out_codec_a = stream_a["codec_name"]
    out_enc_a = stream_a.get("tags", {}).get("encoder", "Unknown")
    print("\n--- Run A Stream Telemetry (frame-accurate sync + hardware encode check) ---")
    print(f"Dimensions:   {out_w_a}x{out_h_a} (Expected 1080x1920)")
    print(f"Packet count: {out_packets_a} (Expected 1800 for 60.000s @ 30fps)")
    print(f"Duration:     {out_dur_a:.6f}s")
    print(f"Codec:        {out_codec_a}  Encoder tag: {out_enc_a}")
    assert out_w_a == 1080 and out_h_a == 1920
    assert out_packets_a == 1800
    assert "h264_amf" in out_enc_a, f"Expected AMF encoder, got {out_enc_a}"

    # ---- classify captured calls ----
    def offset_norm(call):
        bbox = call.get("subject_bbox")
        if not bbox:
            return None
        x0, y0, x1, y1 = bbox[:4]
        hx0, _, hx1, _ = approximate_head_region(bbox)
        return (hx0 + hx1) / 2.0

    with_bbox = [c for c in captured_calls if c.get("subject_bbox")]
    without_bbox = [c for c in captured_calls if not c.get("subject_bbox")]
    with_bbox.sort(key=lambda c: abs((offset_norm(c) or 0.5) - 0.5), reverse=True)

    off_center_samples = with_bbox[:3]
    centered_sample = without_bbox[0] if without_bbox else None
    shortest = min(captured_calls, key=lambda c: c["duration"]) if captured_calls else None

    print(f"\nClips with subject bbox: {len(with_bbox)} / {len(captured_calls)}")
    print(f"Clips with NO bbox (should render static, no ease): {len(without_bbox)}")
    if shortest:
        print(f"Shortest clip's extraction duration: {shortest['duration']:.3f}s "
              f"(video={os.path.basename(shortest['video_file'])}, start={shortest['start_time']:.2f}s)")

    results = {}

    def render_isolate_and_sample(tag, call):
        clip_path = os.path.join(ease_dir, f"{tag}.mp4")
        kwargs = dict(call)
        kwargs["output_file"] = clip_path
        ok = real_extract_clip_segment_ffmpeg(**kwargs)
        assert ok, f"Isolated re-extraction failed for {tag}"

        dur = float(kwargs["duration"])
        bbox = kwargs.get("subject_bbox")
        cx = offset_norm(kwargs) if bbox else None

        sample_times = [round(0.1 * i, 1) for i in range(7) if 0.1 * i < dur]  # 0.0..0.6s, clamped to clip length
        settled_t = max(sample_times[-1], min(dur - 0.05, dur * 0.9))
        settled_frame = os.path.join(ease_dir, f"{tag}_settled.jpg")
        extract_frame(clip_path, settled_t, settled_frame)

        frames = []
        for t in sample_times:
            fpath = os.path.join(ease_dir, f"{tag}_t{t:.1f}.jpg")
            extract_frame(clip_path, t, fpath)
            shift = phase_shift_x(settled_frame, fpath)
            frames.append({
                "t": t,
                "frame": fpath,
                "dx_from_settled_px": round(shift[0], 2) if shift else None,
                "phase_response": round(shift[2], 4) if shift else None,
            })
            print(f"  [{tag}] t={t:.1f}s  dx_from_settled={shift[0] if shift else 'NA'}")

        return {
            "video_file": kwargs["video_file"],
            "start_time": kwargs["start_time"],
            "extraction_duration": dur,
            "subject_bbox": bbox,
            "head_center_x_norm": cx,
            "clip_path": clip_path,
            "settled_probe_t": settled_t,
            "frames": frames,
        }

    print("\n--- Off-center clips: expect large |dx| early, shrinking to ~0 by settle ---")
    results["off_center"] = []
    for i, call in enumerate(off_center_samples):
        tag = f"off_center_{i}_{os.path.splitext(os.path.basename(call['video_file']))[0]}"
        results["off_center"].append(render_isolate_and_sample(tag, call))

    if centered_sample:
        print("\n--- Centered (no-bbox) clip: expect ~0 dx at every sampled t (no ease motion) ---")
        results["centered"] = render_isolate_and_sample(
            f"centered_{os.path.splitext(os.path.basename(centered_sample['video_file']))[0]}", centered_sample
        )
    else:
        results["centered"] = None
        print("\n--- No no-bbox clip found in this plan; skipping centered-clip check ---")

    if shortest and with_bbox and shortest.get("subject_bbox"):
        print("\n--- Shortest real clip (with bbox): verify ease clamps and settles well before clip end ---")
        results["shortest"] = render_isolate_and_sample("shortest", shortest)
    else:
        # Fall back to the shortest clip that DOES have a bbox, since the clamp only
        # matters when there's an ease to clamp in the first place.
        short_with_bbox = min(with_bbox, key=lambda c: c["duration"]) if with_bbox else None
        if short_with_bbox:
            print("\n--- Shortest bbox-bearing clip: verify ease clamps and settles well before clip end ---")
            results["shortest"] = render_isolate_and_sample("shortest", short_with_bbox)
        else:
            results["shortest"] = None

    # ---- Landscape regression spot-check ----
    print("\n" + "=" * 70)
    print("RUN B: Landscape Mode Sanity Check (10s Render) -- must be fully unaffected")
    print("=" * 70)
    out_b = os.path.join(out_dir, "verify_crop_ease_run_b_landscape_sanity.mp4")
    if os.path.isfile(out_b):
        os.remove(out_b)
    t0_b = time.time()
    create_music_video(
        audio_file, prepared_files, selected_beats,
        output_file=out_b, start_time=0.0, end_time=10.0, max_workers=8,
        beat_info=beat_info, lossless_mode=False, gpu_encoder="h264_amf", fps=30.0,
        strict_unique_non_overlap=True, edge_buffer_seconds=0.5, clip_order_mode="journey",
        min_subject_confidence=0.3, image_capture_times=image_times,
        target_resolution=native_res, export_orientation=ORIENTATION_LANDSCAPE,
        transitions_enabled=True, title_card_enabled=True, start_text=title_text, title_theme=THEME_AUTO,
    )
    render_time_b = time.time() - t0_b
    info_b = get_media_info(out_b)
    stream_b = info_b["streams"][0]
    out_w_b, out_h_b = int(stream_b["width"]), int(stream_b["height"])
    out_packets_b = int(stream_b["nb_read_packets"])
    out_enc_b = stream_b.get("tags", {}).get("encoder", "Unknown")
    print(f"Run B: {out_w_b}x{out_h_b}, packets={out_packets_b}, encoder={out_enc_b}, time={render_time_b:.2f}s")
    assert out_w_b == native_res[0] and out_h_b == native_res[1]
    assert out_packets_b == 300
    assert "h264_amf" in out_enc_b

    summary = {
        "status": "SUCCESS",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": "Minisforum UM890 Pro (AMD Ryzen 9 8945HS + Radeon 780M)",
        "run_a_vertical": {
            "output_file": out_a, "render_time_seconds": round(render_time_a, 2),
            "width": out_w_a, "height": out_h_a, "packet_count": out_packets_a,
            "duration": out_dur_a, "codec": out_codec_a, "encoder": out_enc_a,
            "total_captured_clip_extractions": len(captured_calls),
            "clips_with_bbox": len(with_bbox), "clips_without_bbox": len(without_bbox),
        },
        "run_b_landscape_sanity": {
            "output_file": out_b, "render_time_seconds": round(render_time_b, 2),
            "width": out_w_b, "height": out_h_b, "packet_count": out_packets_b, "encoder": out_enc_b,
        },
        "ease_verification": results,
    }
    summary_file = os.path.join(out_dir, "crop_ease_verification_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote verification summary to {summary_file}")
    print("\nALL CROP-EASE HARDWARE VERIFICATIONS COMPLETED")


if __name__ == "__main__":
    main()
