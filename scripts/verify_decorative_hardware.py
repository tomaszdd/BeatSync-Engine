#!/usr/bin/env python3
"""Hardware verification script for designed decorative title card graphics."""

import json
import os
import subprocess
import sys
import time

APP_DIR = r"C:\BeatSyncTest\app\BeatSync-Engine-main"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
SRC_DIR = os.path.join(APP_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from video_processor import (
    analyze_beats_auto,
    create_music_video,
    get_video_files,
    get_video_resolution,
    prepare_visual_sources,
    build_image_capture_time_map,
    is_image_source,
)
from title_theme import (
    THEME_AUTO,
    THEME_JOYFUL_BRIGHT,
    THEME_UPBEAT_ENERGETIC,
    THEME_WARM_SENTIMENTAL,
    compute_mood_signature,
    resolve_theme,
)
from clip_plan import (
    build_render_plan,
    save_render_plan,
    plan_path_for_output,
)


FFMPEG_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffmpeg.exe")
FFPROBE_EXE = os.path.join(APP_DIR, "bin", "ffmpeg", "ffprobe.exe")
if os.path.dirname(FFMPEG_EXE) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = os.path.dirname(FFMPEG_EXE) + os.pathsep + os.environ.get("PATH", "")


def get_media_info(filepath: str) -> dict:
    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_packets,duration,codec_name:stream_tags=encoder",
        "-count_packets",
        "-of", "json",
        filepath,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def get_audio_duration(filepath: str) -> float:
    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        filepath,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    return float(data["format"]["duration"])


def extract_thumbnail(video_path: str, timestamp: float, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def run_verification():
    video_dir = r"D:\Photos\GoPro\2025-10-01 Tereska Birth"
    audio_file = r"C:\BeatSyncTest\audio_60s.mp3"
    out_dir = os.path.join(APP_DIR, "output")
    thumb_dir = os.path.join(out_dir, "decorative_thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)

    print("=" * 70)
    print("DESIGNED DECORATIVE GRAPHICS -- HARDWARE VERIFICATION ON UM890")
    print("=" * 70)

    title_text = "Teresa S. Dunn\n1st October 2025"
    audio_duration = get_audio_duration(audio_file)
    print(f"Input audio duration: {audio_duration:.6f}s")

    video_files = get_video_files(video_dir)
    print(f"Found {len(video_files)} source video files")
    target_res = get_video_resolution(next((p for p in video_files if not is_image_source(p)), video_files[0]))

    # Prepare visual sources
    prep_dir = os.path.join(out_dir, "temp_prep")
    os.makedirs(prep_dir, exist_ok=True)
    pre_paths = list(video_files)
    prepared_files = prepare_visual_sources(
        video_files,
        audio_duration,
        30.0,
        prep_dir,
        edge_buffer_seconds=0.5,
        use_nvenc=True,
        gpu_encoder="h264_amf",
        lossless=False,
        target_size=target_res,
    )
    image_times = build_image_capture_time_map(pre_paths, prepared_files)

    # Analyze beats
    print("\n--- Running Stage 1-4 Beat Analysis ---")
    selected_beats, beat_info = analyze_beats_auto(
        audio_file,
        start_time=0.0,
        end_time=60.0,
        use_gpu=False,
        video_files=prepared_files,
    )
    print(f"Selected {len(selected_beats)} cuts for video")

    # =========================================================================
    # RUN A: AUTO THEME (FULL 60s RENDER) - Warm & Sentimental with Corner Brackets & Leaf
    # =========================================================================
    print("\n" + "=" * 70)
    print("RUN A: Auto Theme ('Warm & Sentimental') - 60s Full Render")
    print("=" * 70)
    out_a = os.path.join(out_dir, "verify_decorative_run_a_auto.mp4")
    if os.path.isfile(out_a):
        try:
            os.remove(out_a)
        except OSError:
            pass

    t0 = time.time()
    res_a = create_music_video(
        audio_file,
        prepared_files,
        selected_beats,
        output_file=out_a,
        start_time=0.0,
        end_time=60.0,
        max_workers=8,
        beat_info=beat_info,
        lossless_mode=False,
        gpu_encoder="h264_amf",
        fps=30.0,
        strict_unique_non_overlap=True,
        edge_buffer_seconds=0.5,
        clip_order_mode="journey",
        min_subject_confidence=0.3,
        image_capture_times=image_times,
        target_resolution=target_res,
        transitions_enabled=True,
        title_card_enabled=True,
        start_text=title_text,
        title_theme=THEME_AUTO,
    )
    render_time_a = time.time() - t0
    print(f"Run A completed in {render_time_a:.2f}s -> {res_a}")

    # Build and save plan for Run A
    plan_path_a = plan_path_for_output(out_a)
    rpd_a = beat_info.get("render_plan_data") or {}
    clips_a = rpd_a.get("clips") or []
    preset_a, mood_sig_a = resolve_theme(THEME_AUTO, clips=clips_a, beat_info=beat_info)

    plan_a = build_render_plan(
        output_file=out_a,
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=rpd_a.get("beat_times", selected_beats),
        segment_durations=rpd_a.get("segment_durations", []),
        clips=clips_a,
        fps=30.0,
        target_resolution=target_res,
        start_time=0.0,
        end_time=60.0,
        gpu_encoder="h264_amf",
        transitions_enabled=True,
        title_card_enabled=True,
        transitions=rpd_a.get("transitions", []),
        title_theme=preset_a.name,
        mood_signature={
            "warmth": mood_sig_a.warmth,
            "energy": mood_sig_a.energy,
            "dominant_emotion": mood_sig_a.dominant_emotion,
            "selected_theme": mood_sig_a.selected_theme,
            "reason": mood_sig_a.reason,
        },
    )
    save_render_plan(plan_a, plan_path_a)
    print(f"Saved Run A plan to {plan_path_a}")

    # Inspect media info for Run A
    media_info_a = get_media_info(out_a)
    vstream_a = media_info_a["streams"][0]
    frame_count_a = int(vstream_a.get("nb_read_packets", 0))
    duration_a = float(vstream_a.get("duration", 0.0))
    encoder_tag_a = vstream_a.get("tags", {}).get("encoder", "unknown")

    print("\n[Run A Media Telemetry]")
    print(f"  Video file: {out_a}")
    print(f"  Frames: {frame_count_a} (Expected: ~1800 at 30fps)")
    print(f"  Duration: {duration_a:.6f}s")
    print(f"  Encoder tag: {encoder_tag_a}")

    # Extract thumbnails for Run A
    print("\n[Run A Thumbnail Extraction]")
    # 1. Within title window (0.5s, 1.5s, 2.5s)
    title_timestamps = [0.5, 1.5, 2.5]
    for t_sec in title_timestamps:
        out_thumb = os.path.join(thumb_dir, f"run_a_warm_title_{t_sec:.1f}s.jpg")
        extract_thumbnail(out_a, t_sec, out_thumb)
        sz = os.path.getsize(out_thumb)
        print(f"  Title window t={t_sec}s: {out_thumb} ({sz:,} bytes)")

    # 2. Plain mid-timeline timestamps (well outside title window and away from transitions)
    # Checking for ZERO trace of decorative graphics or blur/grade leak
    mid_timestamps = [10.0, 30.0, 50.0]
    for t_sec in mid_timestamps:
        out_thumb = os.path.join(thumb_dir, f"run_a_warm_mid_{t_sec:.1f}s.jpg")
        extract_thumbnail(out_a, t_sec, out_thumb)
        sz = os.path.getsize(out_thumb)
        print(f"  Mid-timeline t={t_sec}s: {out_thumb} ({sz:,} bytes)")

    # =========================================================================
    # RUN B: SPOT-CHECK "Joyful & Bright" (10s Render) - Confetti Dots Motif
    # =========================================================================
    print("\n" + "=" * 70)
    print("RUN B: Spot-Check Forced 'Joyful & Bright' (10s)")
    print("=" * 70)
    out_b = os.path.join(out_dir, "verify_decorative_run_b_joyful.mp4")
    if os.path.isfile(out_b):
        try:
            os.remove(out_b)
        except OSError:
            pass

    t0 = time.time()
    res_b = create_music_video(
        audio_file,
        prepared_files,
        selected_beats,
        output_file=out_b,
        start_time=0.0,
        end_time=10.0,
        max_workers=8,
        beat_info=beat_info,
        lossless_mode=False,
        gpu_encoder="h264_amf",
        fps=30.0,
        strict_unique_non_overlap=True,
        edge_buffer_seconds=0.5,
        clip_order_mode="journey",
        min_subject_confidence=0.3,
        image_capture_times=image_times,
        target_resolution=target_res,
        transitions_enabled=True,
        title_card_enabled=True,
        start_text=title_text,
        title_theme=THEME_JOYFUL_BRIGHT,
    )
    render_time_b = time.time() - t0
    print(f"Run B completed in {render_time_b:.2f}s -> {res_b}")

    # Build and save plan for Run B
    plan_path_b = plan_path_for_output(out_b)
    rpd_b = beat_info.get("render_plan_data") or {}
    preset_b, mood_sig_b = resolve_theme(THEME_JOYFUL_BRIGHT, clips=rpd_b.get("clips") or [], beat_info=beat_info)
    plan_b = build_render_plan(
        output_file=out_b,
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=rpd_b.get("beat_times", selected_beats),
        segment_durations=rpd_b.get("segment_durations", []),
        clips=rpd_b.get("clips", []),
        fps=30.0,
        target_resolution=target_res,
        start_time=0.0,
        end_time=10.0,
        gpu_encoder="h264_amf",
        transitions_enabled=True,
        title_card_enabled=True,
        transitions=rpd_b.get("transitions", []),
        title_theme=preset_b.name,
        mood_signature={
            "warmth": mood_sig_b.warmth,
            "energy": mood_sig_b.energy,
            "dominant_emotion": mood_sig_b.dominant_emotion,
            "selected_theme": mood_sig_b.selected_theme,
            "reason": mood_sig_b.reason,
        },
    )
    save_render_plan(plan_b, plan_path_b)

    # Extract thumbnails for Run B
    print("\n[Run B Thumbnail Extraction]")
    for t_sec in [1.0, 6.0]:
        out_thumb = os.path.join(thumb_dir, f"run_b_joyful_{t_sec:.1f}s.jpg")
        extract_thumbnail(out_b, t_sec, out_thumb)
        sz = os.path.getsize(out_thumb)
        print(f"  Run B t={t_sec}s: {out_thumb} ({sz:,} bytes)")

    # =========================================================================
    # RUN C: SPOT-CHECK "Upbeat & Energetic" (10s Render) - Angular Chevrons Motif
    # =========================================================================
    print("\n" + "=" * 70)
    print("RUN C: Spot-Check Forced 'Upbeat & Energetic' (10s)")
    print("=" * 70)
    out_c = os.path.join(out_dir, "verify_decorative_run_c_upbeat.mp4")
    if os.path.isfile(out_c):
        try:
            os.remove(out_c)
        except OSError:
            pass

    t0 = time.time()
    res_c = create_music_video(
        audio_file,
        prepared_files,
        selected_beats,
        output_file=out_c,
        start_time=0.0,
        end_time=10.0,
        max_workers=8,
        beat_info=beat_info,
        lossless_mode=False,
        gpu_encoder="h264_amf",
        fps=30.0,
        strict_unique_non_overlap=True,
        edge_buffer_seconds=0.5,
        clip_order_mode="journey",
        min_subject_confidence=0.3,
        image_capture_times=image_times,
        target_resolution=target_res,
        transitions_enabled=True,
        title_card_enabled=True,
        start_text=title_text,
        title_theme=THEME_UPBEAT_ENERGETIC,
    )
    render_time_c = time.time() - t0
    print(f"Run C completed in {render_time_c:.2f}s -> {res_c}")

    # Build and save plan for Run C
    plan_path_c = plan_path_for_output(out_c)
    rpd_c = beat_info.get("render_plan_data") or {}
    preset_c, mood_sig_c = resolve_theme(THEME_UPBEAT_ENERGETIC, clips=rpd_c.get("clips") or [], beat_info=beat_info)
    plan_c = build_render_plan(
        output_file=out_c,
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=rpd_c.get("beat_times", selected_beats),
        segment_durations=rpd_c.get("segment_durations", []),
        clips=rpd_c.get("clips", []),
        fps=30.0,
        target_resolution=target_res,
        start_time=0.0,
        end_time=10.0,
        gpu_encoder="h264_amf",
        transitions_enabled=True,
        title_card_enabled=True,
        transitions=rpd_c.get("transitions", []),
        title_theme=preset_c.name,
        mood_signature={
            "warmth": mood_sig_c.warmth,
            "energy": mood_sig_c.energy,
            "dominant_emotion": mood_sig_c.dominant_emotion,
            "selected_theme": mood_sig_c.selected_theme,
            "reason": mood_sig_c.reason,
        },
    )
    save_render_plan(plan_c, plan_path_c)

    # Extract thumbnails for Run C
    print("\n[Run C Thumbnail Extraction]")
    for t_sec in [1.0, 6.0]:
        out_thumb = os.path.join(thumb_dir, f"run_c_upbeat_{t_sec:.1f}s.jpg")
        extract_thumbnail(out_c, t_sec, out_thumb)
        sz = os.path.getsize(out_thumb)
        print(f"  Run C t={t_sec}s: {out_thumb} ({sz:,} bytes)")

    # Build and save summary
    summary = {
        "audio_duration": audio_duration,
        "run_a": {
            "output": out_a,
            "render_time_s": render_time_a,
            "frame_count": frame_count_a,
            "duration": duration_a,
            "encoder": encoder_tag_a,
            "theme_name": preset_a.name,
            "decorative_motif": preset_a.decorative_motif_type,
            "thumbnails": {
                f"{t_sec}s": os.path.join(thumb_dir, f"run_a_warm_title_{t_sec:.1f}s.jpg")
                for t_sec in title_timestamps
            },
            "mid_thumbnails": {
                f"{t_sec}s": os.path.join(thumb_dir, f"run_a_warm_mid_{t_sec:.1f}s.jpg")
                for t_sec in mid_timestamps
            },
        },
        "run_b": {
            "output": out_b,
            "render_time_s": render_time_b,
            "theme_name": preset_b.name,
            "decorative_motif": preset_b.decorative_motif_type,
            "thumbnails": {
                "1.0s": os.path.join(thumb_dir, "run_b_joyful_1.0s.jpg"),
                "6.0s": os.path.join(thumb_dir, "run_b_joyful_6.0s.jpg"),
            },
        },
        "run_c": {
            "output": out_c,
            "render_time_s": render_time_c,
            "theme_name": preset_c.name,
            "decorative_motif": preset_c.decorative_motif_type,
            "thumbnails": {
                "1.0s": os.path.join(thumb_dir, "run_c_upbeat_1.0s.jpg"),
                "6.0s": os.path.join(thumb_dir, "run_c_upbeat_6.0s.jpg"),
            },
        },
    }

    summary_file = os.path.join(out_dir, "decorative_verification_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved hardware verification summary to {summary_file}")
    print("\n=== ALL DECORATIVE GRAPHICS HARDWARE VERIFICATIONS COMPLETE! ===")


if __name__ == "__main__":
    run_verification()
