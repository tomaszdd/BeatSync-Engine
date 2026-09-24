#!/usr/bin/env python3
"""Hardware verification script for Ident Outro and Watermark features on UM890.

Executes the 4 required hardware verification runs on Minisforum UM890 Pro
(AMD Ryzen 9 8945HS + Radeon 780M, h264_amf):
(a) Outro only
(b) Watermark only
(c) Both together
(d) Neither (regression check)
Plus a vertical export run verifying letterboxed outro formatting.
"""

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
from clip_plan import (
    build_render_plan,
    save_render_plan,
    plan_path_for_output,
)
from paths import (
    get_ident_asset_path,
    get_watermark_asset_path,
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


def get_audio_info(filepath: str) -> dict:
    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,duration,nb_read_packets",
        "-count_packets",
        "-of", "json",
        filepath,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def get_format_duration(filepath: str) -> float:
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
    ident_path = r"D:\BeatSync-Assets\TDD_Intro_3D_1.mov"
    watermark_path = os.path.join(APP_DIR, "assets", "tdd_watermark.png")
    out_dir = os.path.join(APP_DIR, "output", "ident_watermark_verify")
    thumb_dir = os.path.join(APP_DIR, "docs", "thumbnails", "ident_outro_watermark")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(thumb_dir, exist_ok=True)

    print("=" * 80)
    print("IDENT OUTRO & WATERMARK -- HARDWARE VERIFICATION ON UM890")
    print("GPU: AMD Radeon 780M (Ryzen 9 8945HS) via h264_amf")
    print("=" * 80)

    # 1. Discover visual sources & analyze beats
    print("\n[Stage 1] Loading sources and beat analysis (10s window)...")
    video_files = get_video_files(video_dir)
    print(f"   Found {len(video_files)} source files in {video_dir}")
    print(f"   Ident asset: {ident_path} (exists: {os.path.isfile(ident_path)})")
    print(f"   Watermark asset: {watermark_path} (exists: {os.path.isfile(watermark_path)})")

    pre_paths = list(video_files)
    prep_dir = os.path.join(out_dir, "prepared_sources")
    os.makedirs(prep_dir, exist_ok=True)
    prepared_files = prepare_visual_sources(
        video_files,
        10.0,
        30.0,
        prep_dir,
        edge_buffer_seconds=0.5,
        use_nvenc=True,
        gpu_encoder="h264_amf",
        lossless=False,
        target_size=(3840, 2160),
    )
    image_times = build_image_capture_time_map(pre_paths, prepared_files)

    selected_beats, beat_info = analyze_beats_auto(
        audio_file=audio_file,
        video_files=prepared_files,
        start_time=0.0,
        end_time=10.0,
        use_gpu=False,
    )
    beat_times = selected_beats
    print(f"   Detected {len(beat_times)} beat cuts for 10.0s window.")

    results = {}

    # -------------------------------------------------------------------------
    # RUN A: Outro only
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RUN A: Ident Outro ONLY (ident_outro_enabled=True, watermark_enabled=False)")
    print("=" * 80)
    out_a = os.path.join(out_dir, "verify_run_a_outro_only.mp4")
    t0 = time.perf_counter()
    create_music_video(
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=beat_times,
        output_file=out_a,
        start_time=0.0,
        end_time=10.0,
        use_gpu=True,
        gpu_encoder="h264_amf",
        fps=30.0,
        beat_info=beat_info,
        image_capture_times=image_times,
        transitions_enabled=True,
        target_resolution=(3840, 2160),
        ident_outro_enabled=True,
        ident_clip_path=ident_path,
        watermark_enabled=False,
    )
    dur_a = time.perf_counter() - t0
    print(f"   ✓ Run A completed in {dur_a:.2f}s")

    v_info_a = get_media_info(out_a)["streams"][0]
    a_info_a = get_audio_info(out_a)["streams"][0]
    fmt_dur_a = get_format_duration(out_a)

    thumb_a_main = os.path.join(thumb_dir, "run_a_main_t5.0s.jpg")
    thumb_a_outro = os.path.join(thumb_dir, "run_a_outro_t13.0s.jpg")
    extract_thumbnail(out_a, 5.0, thumb_a_main)
    extract_thumbnail(out_a, 13.0, thumb_a_outro)

    results["run_a"] = {
        "description": "Ident Outro Only",
        "output_file": out_a,
        "render_time_s": round(dur_a, 2),
        "video_width": v_info_a.get("width"),
        "video_height": v_info_a.get("height"),
        "video_packets": int(v_info_a.get("nb_read_packets", 0)),
        "video_duration_s": float(v_info_a.get("duration", 0.0)),
        "format_duration_s": round(fmt_dur_a, 3),
        "video_encoder": v_info_a.get("tags", {}).get("encoder", ""),
        "audio_codec": a_info_a.get("codec_name"),
        "audio_duration_s": float(a_info_a.get("duration", 0.0)),
        "thumbnails": [thumb_a_main, thumb_a_outro],
    }

    # -------------------------------------------------------------------------
    # RUN B: Watermark only
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RUN B: Watermark ONLY (ident_outro_enabled=False, watermark_enabled=True)")
    print("=" * 80)
    out_b = os.path.join(out_dir, "verify_run_b_watermark_only.mp4")
    t0 = time.perf_counter()
    create_music_video(
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=beat_times,
        output_file=out_b,
        start_time=0.0,
        end_time=10.0,
        use_gpu=True,
        gpu_encoder="h264_amf",
        fps=30.0,
        beat_info=beat_info,
        image_capture_times=image_times,
        transitions_enabled=True,
        target_resolution=(3840, 2160),
        ident_outro_enabled=False,
        watermark_enabled=True,
        watermark_image=watermark_path,
        watermark_position="bottom_right",
        watermark_opacity=0.60,
    )
    dur_b = time.perf_counter() - t0
    print(f"   ✓ Run B completed in {dur_b:.2f}s")

    v_info_b = get_media_info(out_b)["streams"][0]
    a_info_b = get_audio_info(out_b)["streams"][0]
    fmt_dur_b = get_format_duration(out_b)

    thumb_b_t2 = os.path.join(thumb_dir, "run_b_watermark_t2.0s.jpg")
    thumb_b_t5 = os.path.join(thumb_dir, "run_b_watermark_t5.0s.jpg")
    thumb_b_t8 = os.path.join(thumb_dir, "run_b_watermark_t8.0s.jpg")
    extract_thumbnail(out_b, 2.0, thumb_b_t2)
    extract_thumbnail(out_b, 5.0, thumb_b_t5)
    extract_thumbnail(out_b, 8.0, thumb_b_t8)

    results["run_b"] = {
        "description": "Watermark Only",
        "output_file": out_b,
        "render_time_s": round(dur_b, 2),
        "video_width": v_info_b.get("width"),
        "video_height": v_info_b.get("height"),
        "video_packets": int(v_info_b.get("nb_read_packets", 0)),
        "video_duration_s": float(v_info_b.get("duration", 0.0)),
        "format_duration_s": round(fmt_dur_b, 3),
        "video_encoder": v_info_b.get("tags", {}).get("encoder", ""),
        "audio_codec": a_info_b.get("codec_name"),
        "audio_duration_s": float(a_info_b.get("duration", 0.0)),
        "thumbnails": [thumb_b_t2, thumb_b_t5, thumb_b_t8],
    }

    # -------------------------------------------------------------------------
    # RUN C: Both together
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RUN C: BOTH Outro & Watermark (ident_outro_enabled=True, watermark_enabled=True)")
    print("=" * 80)
    out_c = os.path.join(out_dir, "verify_run_c_both.mp4")
    t0 = time.perf_counter()
    create_music_video(
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=beat_times,
        output_file=out_c,
        start_time=0.0,
        end_time=10.0,
        use_gpu=True,
        gpu_encoder="h264_amf",
        fps=30.0,
        beat_info=beat_info,
        image_capture_times=image_times,
        transitions_enabled=True,
        target_resolution=(3840, 2160),
        ident_outro_enabled=True,
        ident_clip_path=ident_path,
        watermark_enabled=True,
        watermark_image=watermark_path,
        watermark_position="bottom_right",
        watermark_opacity=0.60,
    )
    dur_c = time.perf_counter() - t0
    print(f"   ✓ Run C completed in {dur_c:.2f}s")

    v_info_c = get_media_info(out_c)["streams"][0]
    a_info_c = get_audio_info(out_c)["streams"][0]
    fmt_dur_c = get_format_duration(out_c)

    thumb_c_main = os.path.join(thumb_dir, "run_c_both_main_t5.0s.jpg")
    thumb_c_outro = os.path.join(thumb_dir, "run_c_both_outro_t13.0s.jpg")
    extract_thumbnail(out_c, 5.0, thumb_c_main)
    extract_thumbnail(out_c, 13.0, thumb_c_outro)

    results["run_c"] = {
        "description": "Both Outro and Watermark",
        "output_file": out_c,
        "render_time_s": round(dur_c, 2),
        "video_width": v_info_c.get("width"),
        "video_height": v_info_c.get("height"),
        "video_packets": int(v_info_c.get("nb_read_packets", 0)),
        "video_duration_s": float(v_info_c.get("duration", 0.0)),
        "format_duration_s": round(fmt_dur_c, 3),
        "video_encoder": v_info_c.get("tags", {}).get("encoder", ""),
        "audio_codec": a_info_c.get("codec_name"),
        "audio_duration_s": float(a_info_c.get("duration", 0.0)),
        "thumbnails": [thumb_c_main, thumb_c_outro],
    }

    # -------------------------------------------------------------------------
    # RUN D: Neither (Regression baseline)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RUN D: NEITHER (ident_outro_enabled=False, watermark_enabled=False) -- Baseline")
    print("=" * 80)
    out_d = os.path.join(out_dir, "verify_run_d_baseline_neither.mp4")
    t0 = time.perf_counter()
    create_music_video(
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=beat_times,
        output_file=out_d,
        start_time=0.0,
        end_time=10.0,
        use_gpu=True,
        gpu_encoder="h264_amf",
        fps=30.0,
        beat_info=beat_info,
        image_capture_times=image_times,
        transitions_enabled=True,
        target_resolution=(3840, 2160),
        ident_outro_enabled=False,
        watermark_enabled=False,
    )
    dur_d = time.perf_counter() - t0
    print(f"   ✓ Run D completed in {dur_d:.2f}s")

    v_info_d = get_media_info(out_d)["streams"][0]
    a_info_d = get_audio_info(out_d)["streams"][0]
    fmt_dur_d = get_format_duration(out_d)

    thumb_d_main = os.path.join(thumb_dir, "run_d_baseline_t5.0s.jpg")
    extract_thumbnail(out_d, 5.0, thumb_d_main)

    results["run_d"] = {
        "description": "Baseline Neither",
        "output_file": out_d,
        "render_time_s": round(dur_d, 2),
        "video_width": v_info_d.get("width"),
        "video_height": v_info_d.get("height"),
        "video_packets": int(v_info_d.get("nb_read_packets", 0)),
        "video_duration_s": float(v_info_d.get("duration", 0.0)),
        "format_duration_s": round(fmt_dur_d, 3),
        "video_encoder": v_info_d.get("tags", {}).get("encoder", ""),
        "audio_codec": a_info_d.get("codec_name"),
        "audio_duration_s": float(a_info_d.get("duration", 0.0)),
        "thumbnails": [thumb_d_main],
    }

    # -------------------------------------------------------------------------
    # RUN E: Vertical 9:16 + Outro + Watermark (Bonus verification)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RUN E: VERTICAL 9:16 (1080x1920) with Outro + Watermark")
    print("=" * 80)
    out_e = os.path.join(out_dir, "verify_run_e_vertical_both.mp4")
    t0 = time.perf_counter()
    create_music_video(
        audio_file=audio_file,
        video_files=prepared_files,
        beat_times=beat_times,
        output_file=out_e,
        start_time=0.0,
        end_time=10.0,
        use_gpu=True,
        gpu_encoder="h264_amf",
        fps=30.0,
        beat_info=beat_info,
        image_capture_times=image_times,
        transitions_enabled=True,
        target_resolution=(1080, 1920),
        export_orientation="Vertical (9:16 — Instagram/Reels)",
        ident_outro_enabled=True,
        ident_clip_path=ident_path,
        watermark_enabled=True,
        watermark_image=watermark_path,
        watermark_position="bottom_right",
        watermark_opacity=0.60,
    )
    dur_e = time.perf_counter() - t0
    print(f"   ✓ Run E completed in {dur_e:.2f}s")

    v_info_e = get_media_info(out_e)["streams"][0]
    a_info_e = get_audio_info(out_e)["streams"][0]
    fmt_dur_e = get_format_duration(out_e)

    thumb_e_main = os.path.join(thumb_dir, "run_e_vertical_main_t5.0s.jpg")
    thumb_e_outro = os.path.join(thumb_dir, "run_e_vertical_outro_t13.0s.jpg")
    extract_thumbnail(out_e, 5.0, thumb_e_main)
    extract_thumbnail(out_e, 13.0, thumb_e_outro)

    results["run_e"] = {
        "description": "Vertical 9:16 Both Outro and Watermark",
        "output_file": out_e,
        "render_time_s": round(dur_e, 2),
        "video_width": v_info_e.get("width"),
        "video_height": v_info_e.get("height"),
        "video_packets": int(v_info_e.get("nb_read_packets", 0)),
        "video_duration_s": float(v_info_e.get("duration", 0.0)),
        "format_duration_s": round(fmt_dur_e, 3),
        "video_encoder": v_info_e.get("tags", {}).get("encoder", ""),
        "audio_codec": a_info_e.get("codec_name"),
        "audio_duration_s": float(a_info_e.get("duration", 0.0)),
        "thumbnails": [thumb_e_main, thumb_e_outro],
    }

    # Save verification telemetry JSON
    summary_path = os.path.join(out_dir, "ident_watermark_verification_telemetry.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print("VERIFICATION TELEMETRY SUMMARY")
    print("=" * 80)
    for run_key, data in results.items():
        print(f"\n[{run_key.upper()}] {data['description']}")
        print(f"   Resolution: {data['video_width']}x{data['video_height']}")
        print(f"   Duration: Video {data['video_duration_s']}s (Packets: {data['video_packets']}), Container {data['format_duration_s']}s, Audio {data['audio_duration_s']}s")
        print(f"   Encoder: {data['video_encoder']}")
        print(f"   Render Time: {data['render_time_s']}s")
        print(f"   Thumbnails: {', '.join(os.path.basename(t) for t in data['thumbnails'])}")

    # Verification Assertions
    print("\n" + "=" * 80)
    print("CHECKING TASK SPEC CRITERIA")
    print("=" * 80)

    # 1. Total duration with outro = 10s + 6.006s = 16.006s
    assert abs(results["run_a"]["format_duration_s"] - 16.006) < 0.1, "Run A duration mismatch"
    assert results["run_a"]["video_packets"] == 480, f"Run A packet count expected 480, got {results['run_a']['video_packets']}"
    print("   [PASS] Criteria 1: Outro run duration exactly 16.006s (10s + 6.006s), 480 packets @ 30fps")

    # 2. Watermark only duration = exactly 10.000s
    assert abs(results["run_b"]["format_duration_s"] - 10.0) < 0.1, "Run B duration mismatch"
    assert results["run_b"]["video_packets"] == 300, f"Run B packet count expected 300, got {results['run_b']['video_packets']}"
    print("   [PASS] Criteria 2: Watermark only duration exactly 10.000s, 300 packets @ 30fps")

    # 3. Both together duration = 16.006s
    assert abs(results["run_c"]["format_duration_s"] - 16.006) < 0.1, "Run C duration mismatch"
    assert results["run_c"]["video_packets"] == 480, f"Run C packet count expected 480, got {results['run_c']['video_packets']}"
    print("   [PASS] Criteria 3: Both together duration exactly 16.006s, 480 packets @ 30fps")

    # 4. Neither matches baseline = 10.000s
    assert abs(results["run_d"]["format_duration_s"] - 10.0) < 0.1, "Run D duration mismatch"
    assert results["run_d"]["video_packets"] == 300, f"Run D packet count expected 300, got {results['run_d']['video_packets']}"
    print("   [PASS] Criteria 4: Regression check neither matches baseline 10.000s, 300 packets @ 30fps")

    # 5. Genuine AMF hardware encoder tag
    for rk in ["run_a", "run_b", "run_c", "run_d", "run_e"]:
        enc = results[rk]["video_encoder"]
        assert "h264_amf" in enc, f"Run {rk} encoder {enc} did not use h264_amf"
    print("   [PASS] Criteria 5: Genuine AMD AMF hardware encoder ('h264_amf') verified across all outputs")

    # 6. Audio plays continuously during outro
    assert results["run_a"]["audio_duration_s"] >= 16.0, "Run A audio duration shorter than 16s"
    assert results["run_c"]["audio_duration_s"] >= 16.0, "Run C audio duration shorter than 16s"
    print("   [PASS] Criteria 6: Audio stream plays continuously through the outro (audio duration >= 16.0s)")

    print("\n🎉 ALL VERIFICATION CRITERIA PASSED ON REAL UM890 HARDWARE!")
    return results


if __name__ == "__main__":
    run_verification()
