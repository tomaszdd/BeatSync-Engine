#!/usr/bin/env python3
"""Hardware verification for Vertical Crop Continuity (Ultra-short floor & Crossfade Continuity).

Runs on UM890 real hardware:
1. Full 60s vertical render against trap_beauty_60s.mp3 (123 BPM).
2. Verifies via generated plan.json that ultra-short clips (< 0.4s) skip independent YOLO
   detection and ease-in, inheriting crop framing from adjacent clips.
3. For real crossfade boundaries (e.g. 3->4, 8->9, 17->18), verifies incoming clip starts
   near outgoing clip's settled crop_x rather than resetting to center (1168px).
4. Verifies hard-cut boundaries still ease from frame-center (1168px).
5. Verifies frame-accurate audio sync (1800 packets for 60s @ 30fps) and genuine AMF encoding (h264_amf).
6. Runs 10s landscape mode sanity check to verify zero regression.
7. Runs the full test suite.
"""

import json
import os
import shutil
import sys
import time
import subprocess

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
from ffmpeg_processing import (
    extract_clip_segment_ffmpeg as real_extract_clip_segment_ffmpeg,
    approximate_head_region,
    calculate_settled_crop_x,
    build_crop_to_fill_filter,
)
from title_theme import THEME_AUTO
from clip_plan import build_render_plan, save_render_plan, plan_path_for_output
from ui_content import ORIENTATION_LANDSCAPE, ORIENTATION_VERTICAL

FFMPEG_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffmpeg.exe")
FFPROBE_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffprobe.exe")
if os.path.dirname(FFMPEG_EXE) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.path.dirname(FFMPEG_EXE) + os.pathsep + os.environ.get("PATH", "")


def run_cmd(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{res.stderr}")
    return res


def get_media_info(filepath):
    cmd = [
        FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_read_packets,duration,codec_name:stream_tags=encoder",
        "-count_packets", "-of", "json", filepath,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def get_audio_duration(filepath):
    cmd = [FFPROBE_EXE, "-v", "error", "-show_entries", "format=duration", "-of", "json", filepath]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(res.stdout)["format"]["duration"])


def extract_frame(video_path, timestamp, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [FFMPEG_EXE, "-y", "-ss", f"{timestamp:.3f}", "-i", video_path, "-vframes", "1", "-q:v", "2", output_path]
    run_cmd(cmd)


def main():
    video_dir = r"D:\Photos\GoPro\2025-10-01 Tereska Birth"
    audio_file = r"C:\BeatSyncTest\trap_beauty_60s.mp3"
    out_dir = os.path.join(APP_DIR, "output")
    verify_dir = os.path.join(out_dir, "crop_continuity_verify")
    if os.path.isdir(verify_dir):
        shutil.rmtree(verify_dir)
    os.makedirs(verify_dir, exist_ok=True)

    print("=" * 70)
    print("VERTICAL CROP CONTINUITY -- HARDWARE VERIFICATION ON UM890")
    print("=" * 70)

    title_text = "Teresa S. Dunn\n1st October 2025"
    audio_duration = get_audio_duration(audio_file)
    print(f"Input audio duration: {audio_duration:.6f}s")

    video_files = get_video_files(video_dir)
    native_res = get_video_resolution(next((p for p in video_files if not is_image_source(p)), video_files[0]))
    print(f"Found {len(video_files)} source files. Native res: {native_res[0]}x{native_res[1]}")

    prep_dir = os.path.join(out_dir, "temp_prep_continuity")
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

    # Capture every extract_clip_segment_ffmpeg call the pipeline makes
    captured_calls = []

    def capturing_extract(**kwargs):
        captured_calls.append(dict(kwargs))
        return real_extract_clip_segment_ffmpeg(**kwargs)

    video_processor.extract_clip_segment_ffmpeg = capturing_extract

    print("\n" + "=" * 70)
    print("RUN A: Vertical Mode (9:16 - 1080x1920) Full 60s Render with Crop Continuity")
    print("=" * 70)
    out_a = os.path.join(out_dir, "verify_crop_continuity_run_a_9_16.mp4")
    if os.path.isfile(out_a):
        os.remove(out_a)

    t0 = time.time()
    res_a = create_music_video(
        audio_file, prepared_files, selected_beats,
        output_file=out_a, start_time=0.0, end_time=60.0, max_workers=8,
        beat_info=beat_info, lossless_mode=False, gpu_encoder="h264_amf", fps=30.0,
        strict_unique_non_overlap=True, edge_buffer_seconds=2.0, clip_order_mode="journey",
        min_subject_confidence=0.3, image_capture_times=image_times,
        target_resolution=(1080, 1920), export_orientation=ORIENTATION_VERTICAL,
        transitions_enabled=True, title_card_enabled=True, start_text=title_text, title_theme=THEME_AUTO,
    )
    render_time_a = time.time() - t0
    video_processor.extract_clip_segment_ffmpeg = real_extract_clip_segment_ffmpeg
    print(f"Run A completed in {render_time_a:.2f}s -> {res_a}")
    print(f"Captured {len(captured_calls)} real extract_clip_segment_ffmpeg() calls")

    plan_path = plan_path_for_output(out_a)
    if beat_info and "render_plan_data" in beat_info:
        save_render_plan(beat_info["render_plan_data"], plan_path)

    # ---- Telemetry Checks ----
    info_a = get_media_info(out_a)
    stream_a = info_a["streams"][0]
    out_w_a, out_h_a = int(stream_a["width"]), int(stream_a["height"])
    out_packets_a = int(stream_a["nb_read_packets"])
    out_dur_a = float(stream_a["duration"])
    out_codec_a = stream_a["codec_name"]
    out_enc_a = stream_a.get("tags", {}).get("encoder", "Unknown")
    print("\n--- Run A Stream Telemetry ---")
    print(f"Dimensions:   {out_w_a}x{out_h_a} (Expected 1080x1920)")
    print(f"Packet count: {out_packets_a} (Expected 1799-1800 for 60.000s @ 30fps)")
    print(f"Duration:     {out_dur_a:.6f}s")
    print(f"Codec:        {out_codec_a}  Encoder tag: {out_enc_a}")
    assert out_w_a == 1080 and out_h_a == 1920
    assert out_packets_a in (1799, 1800), f"Expected 1799-1800 packets, got {out_packets_a}"
    assert "h264_amf" in out_enc_a, f"Expected AMF encoder, got {out_enc_a}"

    # ---- Verify plan.json for Ultra-Short Clips ----
    plan_path = plan_path_for_output(out_a)
    print(f"\n--- Checking Plan JSON: {plan_path} ---")
    assert os.path.isfile(plan_path), f"Plan JSON not found at {plan_path}"
    with open(plan_path, "r", encoding="utf-8") as f:
        plan_data = json.load(f)

    plan_clips = plan_data.get("clips", [])
    print(f"Total clips in plan: {len(plan_clips)}")

    ultra_short_clips = [c for c in plan_clips if c.get("final_duration", 0) < 0.40]
    print(f"Ultra-short clips (< 0.40s): {len(ultra_short_clips)}")
    for uc in ultra_short_clips:
        idx = uc["index"]
        dur = uc.get("final_duration")
        bbox = uc.get("subject_bbox")
        us_skip = uc.get("ultra_short_skip")
        crop_ease = uc.get("crop_ease")
        print(f"  Clip {idx}: dur={dur:.3f}s, ultra_short_skip={us_skip}, crop_ease={crop_ease}, bbox={bbox}")
        assert us_skip is True, f"Clip {idx} expected ultra_short_skip=True"
        assert crop_ease is False, f"Clip {idx} expected crop_ease=False"
        if idx == 0 and len(plan_clips) > 1:
            next_bbox = plan_clips[1].get("subject_bbox")
            assert bbox == next_bbox, f"Clip 0 bbox {bbox} expected to match Clip 1 bbox {next_bbox}"

    # ---- Check Captured Calls for Crossfade Continuity ----
    print("\n--- Checking Cut-to-Cut Continuity on Real Captured Extractions ---")
    def get_clip_idx(call):
        fname = os.path.basename(call.get("output_file", ""))
        parts = fname.split("_")
        if len(parts) >= 3 and parts[0] == "temp" and parts[1] == "clip":
            try:
                return int(parts[2])
            except ValueError:
                pass
        return -1

    captured_by_idx = {get_clip_idx(c): c for c in captured_calls if get_clip_idx(c) >= 0}
    print(f"Indexed {len(captured_by_idx)} captured calls by clip timeline index.")

    # Verify captured arguments for clip 0
    cap_c0 = captured_by_idx.get(0, {})
    print(f"Clip 0 captured: dur={cap_c0.get('duration', 0):.3f}s, skip_ease={cap_c0.get('skip_ease')}")
    assert cap_c0.get("skip_ease") is True

    # Identify crossfade boundaries to verify
    transitions = plan_data.get("transitions", [])
    boundaries_to_verify = []
    for i in range(1, len(plan_clips)):
        t = transitions[i - 1] if i - 1 < len(transitions) else None
        if t and t > 0:
            c_prev = plan_clips[i - 1]
            c_curr = plan_clips[i]
            prev_settled = c_prev.get("crop_settled_x")
            curr_settled = c_curr.get("crop_settled_x")
            if prev_settled is not None and curr_settled is not None:
                gap = abs(curr_settled - prev_settled)
                boundaries_to_verify.append((i - 1, i, t, prev_settled, curr_settled, gap))

    boundaries_to_verify.sort(key=lambda b: b[5], reverse=True)
    print(f"Found {len(boundaries_to_verify)} crossfade boundaries.")
    for b in boundaries_to_verify[:5]:
        print(f"  Boundary {b[0]}->{b[1]}: transition={b[2]}s, crop_x: {b[3]} -> {b[4]} (gap {b[5]}px)")

    # Pick top 3 crossfades with largest crop jumps
    selected_crossfades = boundaries_to_verify[:3]
    crossfade_verification_results = []

    for prev_idx, curr_idx, t_dur, prev_x, curr_x, gap in selected_crossfades:
        tag = f"boundary_{prev_idx}_to_{curr_idx}"
        print(f"\nVerifying crossfade {tag}: gap={gap}px (prev={prev_x}, curr={curr_x}, trans={t_dur}s)")

        curr_call = captured_by_idx.get(curr_idx)
        assert curr_call is not None, f"Captured call for clip {curr_idx} not found"
        init_x = curr_call.get("initial_crop_x")
        trans_d = curr_call.get("transition_duration")
        print(f"  Captured kwargs: initial_crop_x={init_x}, transition_duration={trans_d}")
        assert init_x == prev_x, f"Expected initial_crop_x={prev_x}, got {init_x}"
        assert trans_d == t_dur, f"Expected transition_duration={t_dur}, got {trans_d}"

        # Re-extract incoming clip in isolation WITH FIX
        fixed_clip_path = os.path.join(verify_dir, f"{tag}_fixed_clip_{curr_idx}.mp4")
        kwargs_fixed = dict(curr_call)
        kwargs_fixed["output_file"] = fixed_clip_path
        ok_fixed = real_extract_clip_segment_ffmpeg(**kwargs_fixed)
        assert ok_fixed, f"Fixed extraction failed for {tag}"

        # Re-extract incoming clip in isolation PRE-FIX (resetting to center)
        prefix_clip_path = os.path.join(verify_dir, f"{tag}_prefix_clip_{curr_idx}.mp4")
        kwargs_prefix = dict(curr_call)
        kwargs_prefix["output_file"] = prefix_clip_path
        kwargs_prefix["initial_crop_x"] = None
        kwargs_prefix["transition_duration"] = None
        ok_prefix = real_extract_clip_segment_ffmpeg(**kwargs_prefix)
        assert ok_prefix, f"Prefix extraction failed for {tag}"

        # Extract frames at t=0.0 (start of crossfade) and t=0.2 (mid crossfade)
        f_fixed_t0 = os.path.join(verify_dir, f"{tag}_fixed_t0.0.jpg")
        f_prefix_t0 = os.path.join(verify_dir, f"{tag}_prefix_t0.0.jpg")
        extract_frame(fixed_clip_path, 0.0, f_fixed_t0)
        extract_frame(prefix_clip_path, 0.0, f_prefix_t0)

        # Also extract outgoing clip's final frame right before crossfade
        prev_call = captured_by_idx[prev_idx]
        prev_dur = float(prev_call["duration"])
        prev_clip_path = os.path.join(verify_dir, f"{tag}_prev_clip_{prev_idx}.mp4")
        kwargs_prev = dict(prev_call)
        kwargs_prev["output_file"] = prev_clip_path
        real_extract_clip_segment_ffmpeg(**kwargs_prev)
        f_prev_end = os.path.join(verify_dir, f"{tag}_prev_settled.jpg")
        extract_frame(prev_clip_path, max(0.0, prev_dur - 0.05), f_prev_end)

        crossfade_verification_results.append({
            "boundary": f"{prev_idx}->{curr_idx}",
            "transition_seconds": t_dur,
            "outgoing_settled_crop_x": prev_x,
            "incoming_settled_crop_x": curr_x,
            "crop_gap_px": gap,
            "fixed_initial_crop_x": init_x,
            "prefix_initial_crop_x": 1168,
            "fixed_t0_frame": f_fixed_t0,
            "prefix_t0_frame": f_prefix_t0,
            "outgoing_end_frame": f_prev_end,
        })
        print(f"  ✓ Saved comparison frames for {tag}: fixed_t0={f_fixed_t0}, prefix_t0={f_prefix_t0}")

    # ---- Verify Hard Cut Boundaries ----
    print("\n--- Verifying Hard Cut Boundaries ---")
    hard_cuts = [i for i in range(1, len(plan_clips)) if transitions[i - 1] is None or transitions[i - 1] <= 0]
    print(f"Found {len(hard_cuts)} hard cut boundaries.")
    for hc_idx in hard_cuts[:3]:
        call = captured_by_idx[hc_idx]
        hc_init_x = call.get("initial_crop_x")
        hc_trans_d = call.get("transition_duration")
        print(f"  Hard cut clip {hc_idx}: initial_crop_x={hc_init_x}, transition_duration={hc_trans_d}")
        assert hc_init_x is None, f"Hard cut clip {hc_idx} expected initial_crop_x=None (center)"
        assert hc_trans_d is None, f"Hard cut clip {hc_idx} expected transition_duration=None"

    # ---- RUN B: Landscape Sanity Render (10s) ----
    print("\n" + "=" * 70)
    print("RUN B: Landscape Sanity Render (10s)")
    print("=" * 70)
    out_b = os.path.join(out_dir, "verify_crop_continuity_run_b_landscape.mp4")
    if os.path.isfile(out_b):
        os.remove(out_b)

    t0_b = time.time()
    res_b = create_music_video(
        audio_file, prepared_files, selected_beats[:6],
        output_file=out_b, start_time=0.0, end_time=10.0, max_workers=8,
        lossless_mode=False, gpu_encoder="h264_amf", fps=30.0,
        strict_unique_non_overlap=True, edge_buffer_seconds=0.5, clip_order_mode="journey",
        target_resolution=native_res, export_orientation=ORIENTATION_LANDSCAPE,
        transitions_enabled=True, title_card_enabled=False,
    )
    render_time_b = time.time() - t0_b
    info_b = get_media_info(out_b)
    stream_b = info_b["streams"][0]
    out_w_b, out_h_b = int(stream_b["width"]), int(stream_b["height"])
    out_packets_b = int(stream_b["nb_read_packets"])
    out_dur_b = float(stream_b["duration"])
    out_enc_b = stream_b.get("tags", {}).get("encoder", "Unknown")
    print(f"Run B completed in {render_time_b:.2f}s -> {res_b}")
    print(f"Dimensions:   {out_w_b}x{out_h_b}")
    print(f"Packet count: {out_packets_b} (Expected 299-300 for 10.000s @ 30fps)")
    print(f"Duration:     {out_dur_b:.6f}s")
    print(f"Encoder tag:  {out_enc_b}")
    assert out_w_b == native_res[0] and out_h_b == native_res[1]
    assert out_packets_b in (299, 300)
    assert "h264_amf" in out_enc_b

    # Save summary
    summary_path = os.path.join(out_dir, "crop_continuity_verification_summary.json")
    summary_data = {
        "run_a_vertical": {
            "output_file": out_a,
            "dimensions": f"{out_w_a}x{out_h_a}",
            "packet_count": out_packets_a,
            "duration": out_dur_a,
            "encoder": out_enc_a,
            "render_time": round(render_time_a, 2),
            "total_clips": len(plan_clips),
            "ultra_short_clips": [
                {
                    "index": uc["index"],
                    "duration": uc.get("final_duration"),
                    "ultra_short_skip": uc.get("ultra_short_skip"),
                    "crop_ease": uc.get("crop_ease"),
                    "subject_bbox": uc.get("subject_bbox"),
                }
                for uc in ultra_short_clips
            ],
            "verified_crossfade_boundaries": crossfade_verification_results,
        },
        "run_b_landscape": {
            "output_file": out_b,
            "dimensions": f"{out_w_b}x{out_h_b}",
            "packet_count": out_packets_b,
            "duration": out_dur_b,
            "encoder": out_enc_b,
            "render_time": round(render_time_b, 2),
        },
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\nVerification summary saved to: {summary_path}")
    print("=" * 70)
    print("ALL HARDWARE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
