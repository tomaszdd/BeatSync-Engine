#!/usr/bin/env python3
"""Hardware verification script for Vertical (9:16 - 1080x1920) Export Mode on UM890."""

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
from ui_content import (
    ORIENTATION_LANDSCAPE,
    ORIENTATION_VERTICAL,
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
        "-show_entries", "stream=width,height,nb_read_packets,duration,codec_name:stream_tags=encoder",
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
    thumb_dir = os.path.join(out_dir, "vertical_thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)

    print("=" * 70)
    print("VERTICAL (9:16 - 1080x1920) EXPORT -- HARDWARE VERIFICATION ON UM890")
    print("=" * 70)

    title_text = "Teresa S. Dunn\n1st October 2025"
    audio_duration = get_audio_duration(audio_file)
    print(f"Input audio duration: {audio_duration:.6f}s")

    video_files = get_video_files(video_dir)
    print(f"Found {len(video_files)} source video files")
    native_res = get_video_resolution(next((p for p in video_files if not is_image_source(p)), video_files[0]))
    print(f"Native source resolution: {native_res[0]}x{native_res[1]}")

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
        target_size=native_res,
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
    # RUN A: VERTICAL MODE (9:16 — 1080x1920) FULL 60s RENDER
    # =========================================================================
    print("\n" + "=" * 70)
    print("RUN A: Vertical Mode (9:16 - 1080x1920) Full 60s Render")
    print("=" * 70)
    out_a = os.path.join(out_dir, "verify_vertical_run_a_9_16.mp4")
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
        target_resolution=(1080, 1920),
        export_orientation=ORIENTATION_VERTICAL,
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
        target_resolution=(1080, 1920),
        export_orientation=ORIENTATION_VERTICAL,
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
        },
        text_settings={"start_text": title_text},
    )
    save_render_plan(plan_a, plan_path_a)
    print(f"Saved render plan to {plan_path_a}")

    # Inspect media info for Run A
    info_a = get_media_info(out_a)
    stream_a = info_a["streams"][0]
    out_w_a = int(stream_a["width"])
    out_h_a = int(stream_a["height"])
    out_packets_a = int(stream_a["nb_read_packets"])
    out_dur_a = float(stream_a["duration"])
    out_codec_a = stream_a["codec_name"]
    out_enc_a = stream_a.get("tags", {}).get("encoder", "Unknown")

    print("\n--- Run A Stream Telemetry ---")
    print(f"Dimensions:      {out_w_a}x{out_h_a} (Expected: 1080x1920)")
    print(f"Packet count:    {out_packets_a} (Expected: 1800)")
    print(f"Duration:        {out_dur_a:.6f}s (Expected: ~60.000s)")
    print(f"Codec:           {out_codec_a}")
    print(f"Encoder tag:     {out_enc_a}")
    print(f"File size:       {os.path.getsize(out_a):,} bytes")

    assert out_w_a == 1080 and out_h_a == 1920, f"Dimensions mismatch: got {out_w_a}x{out_h_a}"
    assert out_packets_a == 1800, f"Frame count mismatch: got {out_packets_a}"
    assert "h264_amf" in out_enc_a, f"Expected AMF encoder: got {out_enc_a}"

    # Analyze bboxes in clips
    clips_with_bbox = [c for c in clips_a if c.get("subject_bbox")]
    print(f"\nClips with subject bbox: {len(clips_with_bbox)} / {len(clips_a)}")
    for i, c in enumerate(clips_a[:6]):
        print(f"  Clip {i} ({c.get('source_name')}): bbox={c.get('subject_bbox')}, conf={c.get('subject_confidence', c.get('score'))}")

    # Extract thumbnails for Run A
    print("\n--- Extracting Thumbnails for Run A ---")
    # Title card thumbnails
    t_title_hold = 0.5
    t_title_fade = 1.5
    thumb_hold = os.path.join(thumb_dir, "vertical_title_hold_0.5s.jpg")
    thumb_fade = os.path.join(thumb_dir, "vertical_title_fade_1.5s.jpg")
    extract_thumbnail(out_a, t_title_hold, thumb_hold)
    extract_thumbnail(out_a, t_title_fade, thumb_fade)
    print(f"  Title hold thumb: {thumb_hold} ({os.path.getsize(thumb_hold):,} B)")
    print(f"  Title fade thumb: {thumb_fade} ({os.path.getsize(thumb_fade):,} B)")

    # Timeline clip thumbnails comparing Vertical vs Landscape
    landscape_ref_path = os.path.join(out_dir, "verify_decorative_run_a_auto.mp4")
    has_landscape_ref = os.path.isfile(landscape_ref_path)

    sample_clips_data = []
    # Pick 5 clips across the timeline with subject bboxes
    timeline_cursor = 0.0
    for idx, c in enumerate(clips_a):
        clip_dur = c.get("final_duration", 1.0)
        clip_mid = timeline_cursor + (clip_dur / 2.0)
        timeline_cursor += clip_dur
        bbox = c.get("subject_bbox")
        if bbox is not None and len(sample_clips_data) < 5:
            vert_thumb = os.path.join(thumb_dir, f"clip_{idx:02d}_t{clip_mid:.1f}s_vertical.jpg")
            extract_thumbnail(out_a, clip_mid, vert_thumb)
            
            land_thumb = None
            if has_landscape_ref:
                land_thumb = os.path.join(thumb_dir, f"clip_{idx:02d}_t{clip_mid:.1f}s_landscape_ref.jpg")
                extract_thumbnail(landscape_ref_path, clip_mid, land_thumb)

            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            sample_clips_data.append({
                "clip_index": idx,
                "timestamp": round(clip_mid, 2),
                "source_name": c.get("source_name"),
                "subject_bbox": bbox,
                "subject_center_x": round(cx, 3),
                "subject_center_y": round(cy, 3),
                "vertical_thumb": vert_thumb,
                "vertical_thumb_size": os.path.getsize(vert_thumb),
                "landscape_thumb": land_thumb,
                "landscape_thumb_size": os.path.getsize(land_thumb) if land_thumb and os.path.isfile(land_thumb) else None,
            })
            print(f"  Sample Clip {idx} at {clip_mid:.1f}s: source={c.get('source_name')}, cx={cx:.3f}, vert_thumb={vert_thumb}")

    # Post-title sharp thumbnails
    sharp_thumbs = []
    for t_sharp in [5.0, 25.0, 50.0]:
        st = os.path.join(thumb_dir, f"vertical_mid_t{t_sharp:.1f}s.jpg")
        extract_thumbnail(out_a, t_sharp, st)
        sharp_thumbs.append({
            "timestamp": t_sharp,
            "path": st,
            "size": os.path.getsize(st),
        })

    # =========================================================================
    # RUN B: LANDSCAPE SANITY SPOT-CHECK (Ensure no regression)
    # =========================================================================
    print("\n" + "=" * 70)
    print("RUN B: Landscape Mode Sanity Check (10s Render)")
    print("=" * 70)
    out_b = os.path.join(out_dir, "verify_vertical_run_b_landscape_sanity.mp4")
    if os.path.isfile(out_b):
        try:
            os.remove(out_b)
        except OSError:
            pass

    t0_b = time.time()
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
        target_resolution=native_res,
        export_orientation=ORIENTATION_LANDSCAPE,
        transitions_enabled=True,
        title_card_enabled=True,
        start_text=title_text,
        title_theme=THEME_AUTO,
    )
    render_time_b = time.time() - t0_b
    print(f"Run B completed in {render_time_b:.2f}s -> {res_b}")

    info_b = get_media_info(out_b)
    stream_b = info_b["streams"][0]
    out_w_b = int(stream_b["width"])
    out_h_b = int(stream_b["height"])
    out_packets_b = int(stream_b["nb_read_packets"])
    out_codec_b = stream_b["codec_name"]
    out_enc_b = stream_b.get("tags", {}).get("encoder", "Unknown")

    print("\n--- Run B Stream Telemetry (Landscape Sanity) ---")
    print(f"Dimensions:      {out_w_b}x{out_h_b} (Expected: {native_res[0]}x{native_res[1]})")
    print(f"Packet count:    {out_packets_b} (Expected: 300 for 10s)")
    print(f"Codec:           {out_codec_b}")
    print(f"Encoder tag:     {out_enc_b}")
    print(f"File size:       {os.path.getsize(out_b):,} bytes")

    assert out_w_b == native_res[0] and out_h_b == native_res[1], f"Landscape dimensions mismatch: got {out_w_b}x{out_h_b}"
    assert out_packets_b == 300, f"Landscape packet count mismatch: got {out_packets_b}"
    assert "h264_amf" in out_enc_b, f"Expected AMF encoder: got {out_enc_b}"

    # Compile verification summary
    summary = {
        "status": "SUCCESS",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": "Minisforum UM890 Pro (AMD Ryzen 9 8945HS + Radeon 780M)",
        "run_a_vertical": {
            "output_file": out_a,
            "render_time_seconds": round(render_time_a, 2),
            "width": out_w_a,
            "height": out_h_a,
            "aspect_ratio": "9:16",
            "packet_count": out_packets_a,
            "duration": out_dur_a,
            "fps": 30.0,
            "codec": out_codec_a,
            "encoder": out_enc_a,
            "file_size_bytes": os.path.getsize(out_a),
            "total_clips": len(clips_a),
            "clips_with_subject_bbox": len(clips_with_bbox),
            "title_hold_thumb": thumb_hold,
            "title_fade_thumb": thumb_fade,
            "sample_clips": sample_clips_data,
            "sharp_thumbs": sharp_thumbs,
        },
        "run_b_landscape_sanity": {
            "output_file": out_b,
            "render_time_seconds": round(render_time_b, 2),
            "width": out_w_b,
            "height": out_h_b,
            "packet_count": out_packets_b,
            "codec": out_codec_b,
            "encoder": out_enc_b,
            "file_size_bytes": os.path.getsize(out_b),
        },
    }

    summary_file = os.path.join(out_dir, "vertical_verification_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote verification summary to {summary_file}")
    print("\nALL HARDWARE VERIFICATIONS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    run_verification()
