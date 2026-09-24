#!/usr/bin/env python3
"""
FFmpeg Processing Module - Frame-Accurate Video Operations
- Frame-perfect segment extraction
- Zero timing drift
"""

import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import subprocess
import time
import json
import random
import shutil
import uuid
import re
from typing import Tuple, List, Sequence, Dict, Any, Optional

try:
    from title_theme import (
        ThemePreset,
        resolve_theme,
        THEME_AUTO,
        THEME_PRESETS,
        THEME_WARM_SENTIMENTAL,
    )
except ImportError:
    ThemePreset = None
    resolve_theme = None
    THEME_AUTO = "Auto (AI mood match)"
    THEME_PRESETS = {}
    THEME_WARM_SENTIMENTAL = "Warm & Sentimental"


from logger import (
    setup_environment,
    FFMPEG_EXE as FFMPEG_PATH,
    check_nvenc as check_nvenc_support,
)
from gpu_cpu_utils import MAX_THREADS

try:
    from paths import (
        DEFAULT_IDENT_ASSET_PATH,
        DEFAULT_WATERMARK_ASSET_PATH,
        get_ident_asset_path,
        get_watermark_asset_path,
    )
except ImportError:
    DEFAULT_IDENT_ASSET_PATH = os.environ.get(
        'BEATSYNC_IDENT_ASSET_PATH',
        r'D:\BeatSync-Assets\TDD_Intro_3D_1.mov'
    )
    DEFAULT_WATERMARK_ASSET_PATH = os.path.join(
        os.path.dirname(current_dir), 'assets', 'tdd_watermark.png'
    )
    def get_ident_asset_path() -> str:
        return DEFAULT_IDENT_ASSET_PATH
    def get_watermark_asset_path() -> str:
        return DEFAULT_WATERMARK_ASSET_PATH

# Initialize environment
setup_environment()

# Set up FFPROBE_PATH based on FFMPEG_PATH
FFPROBE_PATH = FFMPEG_PATH.replace('ffmpeg.exe', 'ffprobe.exe')
if not os.path.exists(FFMPEG_PATH):
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        FFMPEG_PATH = system_ffmpeg
if not os.path.exists(FFPROBE_PATH):
    system_ffprobe = shutil.which('ffprobe')
    if system_ffprobe:
        FFPROBE_PATH = system_ffprobe



NVENC_QUALITY_CQ = '1'
NVENC_LOOKAHEAD = '32'
NVENC_AQ_STRENGTH = '12'


def _run_media_command(cmd: List[str], timeout: int, low_priority: bool = False) -> subprocess.CompletedProcess[str]:
    """Run an FFmpeg/FFprobe command with consistent capture settings."""
    creationflags = 0
    if low_priority and sys.platform == 'win32':
        # Let the OS scheduler favor other processes (e.g. the browser playing a video) over this one.
        creationflags = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


def _safe_remove_file(path: str | None) -> None:
    """Best-effort removal for temporary media files."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            print(f"   ⚠️  Could not remove temporary file {os.path.basename(path)}: {e}")


def _short_ffmpeg_error(stderr: str, max_chars: int = 2200) -> str:
    """Return the useful tail of FFmpeg stderr without flooding the UI/log."""
    if not stderr:
        return ""
    text = stderr.strip()
    if len(text) <= max_chars:
        return text
    return "..." + text[-max_chars:]


def _fmt_seconds(seconds: float) -> str:
    try:
        value = float(seconds)
    except Exception:
        value = 0.0
    if value < 1.0:
        return f"{value * 1000:.0f}ms"
    return f"{value:.1f}s"


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _extract_scene_times(stderr: str) -> List[float]:
    """Parse showinfo pts_time values from FFmpeg stderr."""
    scene_changes: List[float] = []
    for line in stderr.split('\n'):
        if 'pts_time:' in line:
            match = re.search(r'pts_time:([\d.]+)', line)
            if match:
                try:
                    scene_changes.append(float(match.group(1)))
                except ValueError:
                    pass
    scene_changes = sorted(set(round(t, 3) for t in scene_changes if t >= 0.0))
    cleaned: List[float] = []
    for t in scene_changes:
        if not cleaned or t - cleaned[-1] >= 0.08:
            cleaned.append(t)
    return cleaned


def get_nvenc_quality_args(gpu_encoder: str, include_pix_fmt: bool = True) -> List[str]:
    """Return high-quality NVENC settings for H.264/HEVC exports."""
    args = [
        '-c:v', gpu_encoder,
        '-preset', 'p7',
        '-tune', 'uhq' if gpu_encoder == 'hevc_nvenc' else 'hq',
        '-rc', 'vbr',
        '-b:v', '0',
        '-cq', NVENC_QUALITY_CQ,
        '-multipass', 'fullres',
        '-rc-lookahead', NVENC_LOOKAHEAD,
        '-spatial_aq', '1',
        '-temporal_aq', '1',
        '-aq-strength', NVENC_AQ_STRENGTH,
        '-b_ref_mode', 'middle',
    ]

    if gpu_encoder == 'h264_nvenc':
        args.extend(['-profile:v', 'high'])
    elif gpu_encoder == 'hevc_nvenc':
        args.extend(['-profile:v', 'main'])

    if include_pix_fmt:
        args.extend(['-pix_fmt', 'yuv420p'])

    return args


def get_amf_quality_args(gpu_encoder: str, include_pix_fmt: bool = True) -> List[str]:
    """Return high-quality AMD AMF settings for H.264/HEVC exports."""
    args = [
        '-c:v', gpu_encoder,
        '-quality', 'quality',
        '-rc', 'vbr_peak',
        '-qp_i', '18',
        '-qp_p', '20',
        '-b:v', '0',
        '-usage', 'transcoding',
    ]

    if gpu_encoder == 'h264_amf':
        args.extend(['-profile:v', 'high'])
    elif gpu_encoder == 'hevc_amf':
        args.extend(['-profile:v', 'main'])

    if include_pix_fmt:
        args.extend(['-pix_fmt', 'yuv420p'])

    return args


def get_cpu_h264_quality_args(include_pix_fmt: bool = True, threads: int | None = None) -> List[str]:
    """Return lossless CPU H.264 settings."""
    args = [
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-crf', '0',
    ]
    if include_pix_fmt:
        args.extend(['-pix_fmt', 'yuv420p'])
    args.extend(['-threads', str(threads or MAX_THREADS)])
    return args


def get_video_duration(video_file: str) -> float:
    """Get the duration of a video file using ffprobe."""
    try:
        probe_cmd = [
            FFPROBE_PATH,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_file
        ]
        
        result = _run_media_command(probe_cmd, timeout=10)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"   ⚠️  Could not get video duration with ffprobe: {e}")
        return 10.0  # Default fallback


def get_video_fps(video_file: str) -> float:
    """Get the FPS of a video file using ffprobe."""
    try:
        probe_cmd = [
            FFPROBE_PATH,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=r_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_file
        ]
        
        result = _run_media_command(probe_cmd, timeout=10)
        fps_str = result.stdout.strip()
        
        # Parse fraction (e.g., "30000/1001" or "30/1")
        if '/' in fps_str:
            num, den = fps_str.split('/')
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)
        
        return fps
    except Exception as e:
        print(f"   ⚠️  Could not get video FPS with ffprobe: {e}")
        return 30.0  # Default fallback


def get_video_resolution(video_file: str) -> Tuple[int, int]:
    """Get the resolution (width, height) of a video file using ffprobe."""
    try:
        probe_cmd = [
            FFPROBE_PATH,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            video_file
        ]
        
        result = _run_media_command(probe_cmd, timeout=10)
        data = json.loads(result.stdout)
        
        width = data['streams'][0]['width']
        height = data['streams'][0]['height']
        
        return (width, height)
    except Exception as e:
        print(f"   ⚠️  Could not get video resolution with ffprobe: {e}")
        return (1920, 1080)  # Default fallback


def build_fit_scale_filter(width: int, height: int, color: str = "black") -> str:
    """Scale a source into ``width`` x ``height`` while keeping its aspect ratio.

    Portrait or otherwise non-matching sources are letter-/pillar-boxed with
    ``color`` bars instead of being stretched to fill the frame. ``setsar=1``
    keeps the output pixel-square so later concat/encode steps stay consistent.
    """
    width = int(width)
    height = int(height)
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={color},setsar=1"
    )


def approximate_head_region(
    subject_bbox: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """Return a conservative head proxy from the top 20% of a person bbox.

    With no keypoints or face detector, the top slice has the same horizontal
    limits as the person box. Keeping that full width is intentionally safer
    than assuming the head is centered: leaning, lying, and reaching subjects
    can put a face near either horizontal edge.
    """
    x0, y0, x1, y1 = (float(value) for value in subject_bbox[:4])
    return x0, y0, x1, y0 + max(0.0, y1 - y0) * 0.20


# Nominal duration of the per-clip crop settle-in ease (see build_crop_to_fill_filter).
# Kept mid-range of the requested 0.3-0.5s window; short clips scale this down.
_CROP_EASE_DURATION_S = 0.4

# Below this pixel gap, a subject-aware offset is treated as "already centered" --
# not worth an ease (avoids pointless sub-pixel motion on effectively-centered crops).
_CROP_EASE_MIN_OFFSET_PX = 2

# Floor below which clips are considered ultra-short. Ultra-short clips do not
# visually register a "settle" and shouldn't pay the cost/risk of independent
# subject detection and ease.
_ULTRA_SHORT_CLIP_FLOOR = 0.40


def _eased_crop_x_expr(start_x: int, end_x: int, ease_seconds: float) -> str:
    """FFmpeg 'x' expression that smoothstep-eases start_x -> end_x over ease_seconds.

    Uses the standard smoothstep curve 3p^2 - 2p^3 on progress p = t/ease_seconds.
    'min(1, ...)' clamps p at 1 once the ease window has elapsed, so the same
    expression naturally holds at end_x for the rest of the clip -- no separate
    branch/if() needed. 't' is seconds since this filtergraph's own start, which
    is per-clip here since each extracted clip is trimmed and PTS-reset upstream.
    """
    if start_x == end_x:
        return str(end_x)
    ease_seconds = max(0.001, float(ease_seconds))
    # ',' is the filtergraph filter-separator, so the comma inside min(...)'s
    # argument list must be backslash-escaped or ffmpeg splits the filter chain
    # here instead of parsing it as part of crop's x value.
    p = f"min(1\\,t/{ease_seconds:.4f})"
    smoothstep = f"(3*{p}^2-2*{p}^3)"
    return f"({start_x}+({end_x}-{start_x})*{smoothstep})"


def calculate_settled_crop_x(
    source_width: int,
    source_height: int,
    target_width: int = 1080,
    target_height: int = 1920,
    subject_bbox: Tuple[float, float, float, float] | None = None,
) -> int:
    """Calculate the final settled crop x offset (in pixels) for a vertical clip."""
    sw = max(2, int(source_width))
    sh = max(2, int(source_height))
    tw = max(2, int(target_width))
    th = max(2, int(target_height))

    scale_factor = max(tw / float(sw), th / float(sh))
    scaled_w = int(round(sw * scale_factor / 2.0)) * 2
    scaled_h = int(round(sh * scale_factor / 2.0)) * 2
    scaled_w = max(tw, scaled_w)
    scaled_h = max(th, scaled_h)

    if subject_bbox and len(subject_bbox) >= 4:
        head_x0, _, head_x1, _ = approximate_head_region(subject_bbox)
        cx_norm = max(0.0, min(1.0, (head_x0 + head_x1) / 2.0))
        head_width = max(0.0, min(1.0, head_x1 - head_x0))
        protected_width = min(1.0, head_width * 1.50)
        fill_window_width = tw / float(scaled_w)
        if protected_width > fill_window_width:
            fit_scale = tw / max(1.0, sw * protected_width)
            fit_w = max(tw, int(round(sw * fit_scale / 2.0)) * 2)
            fit_h = max(2, int(round(sh * fit_scale / 2.0)) * 2)
            if fit_h < th:
                max_fit_x = max(0, fit_w - tw)
                fit_x = int(round((cx_norm * fit_w - tw / 2.0) / 2.0)) * 2
                return max(0, min(max_fit_x, fit_x))
    else:
        cx_norm = 0.5

    max_x = max(0, scaled_w - tw)
    if max_x > 0:
        crop_center_x = cx_norm * scaled_w
        crop_x = int(round((crop_center_x - tw / 2.0) / 2.0)) * 2
        return max(0, min(max_x, crop_x))
    return 0


def build_crop_to_fill_filter(
    source_width: int,
    source_height: int,
    target_width: int = 1080,
    target_height: int = 1920,
    subject_bbox: Tuple[float, float, float, float] | None = None,
    clip_duration: float | None = None,
    initial_crop_x: int | None = None,
    transition_duration: float | None = None,
    skip_ease: bool = False,
) -> str:
    """Scale source to fill target canvas and crop horizontally/vertically.

    For vertical mode (e.g. 1080x1920), scales source to match target height,
    then crops target_width horizontally centered on the detected subject bbox
    (falling back to geometric center 0.5 when no bbox is available), clamped
    so the crop window never exceeds source boundaries.

    When subject_bbox yields a horizontal offset meaningfully different from
    start position, the crop's x position eases in to that final offset
    over ~0.3-0.5s (smoothstep, not linear), then holds static.

    If initial_crop_x is provided (e.g. at a crossfade boundary), easing starts
    from the outgoing clip's final crop position and extends over
    (transition_duration + 0.4s) clamped to clip duration, so the blending
    streams share framing during the blend window and only diverge smoothly.
    At a hard cut (initial_crop_x is None), easing starts from frame center.
    For ultra-short clips (< 0.4s) or when skip_ease is True, easing is skipped.
    """
    if skip_ease or (clip_duration is not None and clip_duration > 0 and clip_duration < _ULTRA_SHORT_CLIP_FLOOR):
        ease_duration = 0.0
    elif transition_duration is not None and transition_duration > 0:
        ease_duration = transition_duration + _CROP_EASE_DURATION_S
        if clip_duration is not None and clip_duration > 0:
            ease_duration = min(ease_duration, max(transition_duration, clip_duration * 0.75))
    else:
        ease_duration = _CROP_EASE_DURATION_S
        if clip_duration is not None and clip_duration > 0 and clip_duration < 2 * _CROP_EASE_DURATION_S:
            ease_duration = min(_CROP_EASE_DURATION_S, clip_duration * 0.4)

    sw = max(2, int(source_width))
    sh = max(2, int(source_height))
    tw = max(2, int(target_width))
    th = max(2, int(target_height))

    # Scale factor to fill the target canvas completely.
    scale_factor = max(tw / float(sw), th / float(sh))
    scaled_w = int(round(sw * scale_factor / 2.0)) * 2
    scaled_h = int(round(sh * scale_factor / 2.0)) * 2
    scaled_w = max(tw, scaled_w)
    scaled_h = max(th, scaled_h)

    # Subject center in normalized coordinates (0..1)
    if subject_bbox and len(subject_bbox) >= 4:
        x0, y0, x1, y1 = subject_bbox[:4]
        head_x0, _, head_x1, _ = approximate_head_region(subject_bbox)
        cx_norm = max(0.0, min(1.0, (head_x0 + head_x1) / 2.0))
        cy_norm = max(0.0, min(1.0, (y0 + y1) / 2.0))
    else:
        cx_norm = 0.5
        cy_norm = 0.5

    # Give detected subjects 25% breathing room on each horizontal edge. If
    # that protected extent is wider than a fill crop can show, zoom out only
    # as much as necessary and accept modest top/bottom letterboxing.
    if subject_bbox and len(subject_bbox) >= 4:
        head_width = max(0.0, min(1.0, head_x1 - head_x0))
        protected_width = min(1.0, head_width * 1.50)
        fill_window_width = tw / float(scaled_w)
        if protected_width > fill_window_width:
            fit_scale = tw / max(1.0, sw * protected_width)
            fit_w = max(tw, int(round(sw * fit_scale / 2.0)) * 2)
            fit_h = max(2, int(round(sh * fit_scale / 2.0)) * 2)
            if fit_h < th:
                max_fit_x = max(0, fit_w - tw)
                fit_x = int(round((cx_norm * fit_w - tw / 2.0) / 2.0)) * 2
                fit_x = max(0, min(max_fit_x, fit_x))
                fit_center_x = int(round((0.5 * fit_w - tw / 2.0) / 2.0)) * 2
                fit_center_x = max(0, min(max_fit_x, fit_center_x))
                if initial_crop_x is not None:
                    fit_start_x = max(0, min(max_fit_x, int(initial_crop_x)))
                else:
                    fit_start_x = fit_center_x
                if ease_duration <= 0.001 or abs(fit_x - fit_start_x) < _CROP_EASE_MIN_OFFSET_PX:
                    fit_x_expr = str(fit_x)
                else:
                    fit_x_expr = _eased_crop_x_expr(fit_start_x, fit_x, ease_duration)
                return (
                    f"scale={fit_w}:{fit_h},crop={tw}:{fit_h}:{fit_x_expr}:0,"
                    f"pad={tw}:{th}:0:(oh-ih)/2:color=black,setsar=1"
                )

    # Horizontal crop offset
    max_x = max(0, scaled_w - tw)
    if max_x > 0:
        crop_center_x = cx_norm * scaled_w
        crop_x = int(round((crop_center_x - tw / 2.0) / 2.0)) * 2
        crop_x = max(0, min(max_x, crop_x))
        neutral_x = int(round((0.5 * scaled_w - tw / 2.0) / 2.0)) * 2
        neutral_x = max(0, min(max_x, neutral_x))
        if initial_crop_x is not None:
            start_x = max(0, min(max_x, int(initial_crop_x)))
        else:
            start_x = neutral_x
        if ease_duration <= 0.001 or abs(crop_x - start_x) < _CROP_EASE_MIN_OFFSET_PX:
            crop_x_expr = str(crop_x)
        else:
            crop_x_expr = _eased_crop_x_expr(start_x, crop_x, ease_duration)
    else:
        crop_x_expr = "0"

    # Vertical crop offset
    max_y = max(0, scaled_h - th)
    if max_y > 0:
        crop_center_y = cy_norm * scaled_h
        crop_y = int(round((crop_center_y - th / 2.0) / 2.0)) * 2
        crop_y = max(0, min(max_y, crop_y))
    else:
        crop_y = 0

    return f"scale={scaled_w}:{scaled_h},crop={tw}:{th}:{crop_x_expr}:{crop_y},setsar=1"


def create_looping_image_video(image_file: str, output_file: str, duration: float,
                               fps: float, use_nvenc: bool = False,
                               gpu_encoder: str = 'h264_nvenc', lossless: bool = False,
                               target_size: Tuple[int, int] | None = None) -> str:
    """Turn a still image into a silent CFR MP4 source for the render pipeline."""
    duration = max(0.1, float(duration))
    fps = max(1.0, float(fps))
    # Scale to the final output size now (not the native photo resolution) so we don't
    # push multi-megapixel frames through the filter/encoder for the whole song length.
    if target_size:
        tw, th = target_size
        if th > tw:
            # Vertical mode: smart crop-to-fill
            try:
                img_w, img_h = get_video_resolution(image_file)
            except Exception:
                img_w, img_h = tw, th
            scale_filter = build_crop_to_fill_filter(img_w, img_h, tw, th)
        else:
            scale_filter = build_fit_scale_filter(tw, th)
    else:
        scale_filter = "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"

    # HEIC/WebP/etc. can be very expensive to re-decode on every looped frame with
    # some FFmpeg builds. Decode the source once to a plain PNG and loop that instead.
    decoded_frame = os.path.join(os.path.dirname(output_file) or ".", f"_decoded_{uuid.uuid4().hex}.png")
    decode_result = _run_media_command(
        [FFMPEG_PATH, '-y', '-i', image_file, '-frames:v', '1', decoded_frame], timeout=60
    )
    loop_source = decoded_frame if decode_result.returncode == 0 and os.path.exists(decoded_frame) else image_file

    cmd = [
        FFMPEG_PATH,
        '-loop', '1',
        '-i', loop_source,
        '-vf', f"{scale_filter},fps={fps}",
        '-t', f'{duration:.6f}',
    ]
    if lossless:
        # Exact reproduction is required before the ProRes conversion step.
        cmd.extend(['-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage', '-crf', '0', '-pix_fmt', 'yuv420p'])
    elif use_nvenc:
        if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
            cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
        elif gpu_encoder in ('h264_amf', 'hevc_amf'):
            cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
    else:
        # This intermediate gets re-encoded again during clip extraction, so lossy is fine and much faster.
        cmd.extend(['-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage', '-crf', '16', '-pix_fmt', 'yuv420p'])
    cmd.extend([
        '-an',
        '-fps_mode', 'cfr',
        '-threads', str(MAX_THREADS),
        '-y',
        output_file,
    ])
    try:
        result = _run_media_command(cmd, timeout=180)
        if result.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            raise RuntimeError(
                f"Could not create video source from image {os.path.basename(image_file)}: "
                f"{_short_ffmpeg_error(result.stderr)}"
            )
        return output_file
    finally:
        _safe_remove_file(decoded_frame)


def seconds_to_frame_count(seconds: float, fps: float) -> int:
    """
    Convert seconds to exact frame count.
    This ensures frame-accurate timing with no drift.
    """
    return int(round(seconds * fps))


def frame_count_to_seconds(frames: int, fps: float) -> float:
    """
    Convert frame count back to exact seconds.
    This is the EXACT duration for the frame count.
    """
    return frames / fps


_TEXT_POSITIONS = {
    'top_left': ('40', '40'),
    'top_center': ('(w-text_w)/2', '40'),
    'top_right': ('w-text_w-40', '40'),
    'middle_left': ('40', '(h-text_h)/2'),
    'middle_center': ('(w-text_w)/2', '(h-text_h)/2'),
    'middle_right': ('w-text_w-40', '(h-text_h)/2'),
    'bottom_left': ('40', 'h-text_h-40'),
    'bottom_center': ('(w-text_w)/2', 'h-text_h-40'),
    'bottom_right': ('w-text_w-40', 'h-text_h-40'),
}


def _escape_drawtext_value(text: str) -> str:
    """Escape user text for FFmpeg's drawtext filter."""
    return str(text).replace('\\', r'\\').replace("'", r"\'").replace(':', r'\:').replace(',', r'\,').replace('\n', r'\n')


def _escape_drawtext_fontfile(path: str) -> str:
    """Escape a Windows font path for use inside a drawtext filter string."""
    return str(path).replace('\\', '/').replace(':', r'\:')


DEFAULT_TEXT_FONT_FILE = os.path.join(
    os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'arial.ttf'
)


def _title_font_size(text: str, frame_w: int, frame_h: int) -> int:
    """Font size so a short title fills at least ~1/3 of the frame.

    drawtext has no auto-fit, so we size from the character count: Arial-like
    faces advance roughly 0.5 * fontsize per glyph. We aim for a text width of
    ~1/3 of the frame (or ~half in portrait), keep a generous floor so it always
    reads big, and cap it so it never grows past the frame width or height limits.
    """
    lines = [ln for ln in str(text or '').strip().splitlines() if ln.strip()]
    n = max(1, max((len(ln) for ln in lines), default=len(str(text or '').strip())))
    min_dim = min(frame_w, frame_h)
    aim_width = 0.50 * min_dim if frame_w < frame_h else 0.34 * frame_w
    by_width = aim_width / (0.5 * n)
    floor = min_dim / 15.0                          # always clearly visible
    ceil_w = (0.85 * frame_w) / (0.5 * n)           # never overflow the frame
    ceil_h = frame_h / 4.0                          # never taller than a quarter
    size = min(max(by_width, floor), ceil_w, ceil_h)
    return int(max(16, round(size)))


def compute_watermark_layout(
    frame_w: int,
    frame_h: int,
    wm_w_raw: int,
    wm_h_raw: int,
    position: str = 'bottom_right',
) -> Tuple[int, int, int, int]:
    """Calculate scaled watermark dimensions and (x, y) coordinates.

    Spec requirements:
    - ~8-10% of frame width (8.5% in landscape, 10% in vertical 9:16).
    - Aspect ratio preserved.
    - Default position bottom-right with ~2% padding from edge.
    - All dimensions rounded to even integers for clean video alignment.
    """
    is_vertical = frame_h > frame_w
    if is_vertical:
        width_ratio = 0.10
        pad_x_ratio = 0.025
        pad_y_ratio = 0.025
    else:
        width_ratio = 0.085
        pad_x_ratio = 0.020
        pad_y_ratio = 0.020

    raw_aspect = float(wm_h_raw) / float(max(1, wm_w_raw))
    target_w = max(32, int(round(frame_w * width_ratio)))
    if target_w % 2 != 0:
        target_w += 1

    target_h = max(24, int(round(target_w * raw_aspect)))
    if target_h % 2 != 0:
        target_h += 1

    pad_x = max(16, int(round(frame_w * pad_x_ratio)))
    if pad_x % 2 != 0:
        pad_x += 1
    pad_y = max(16, int(round(frame_h * pad_y_ratio)))
    if pad_y % 2 != 0:
        pad_y += 1

    pos = str(position or 'bottom_right').lower()
    if pos == 'top_left':
        x = pad_x
        y = pad_y
    elif pos == 'top_right':
        x = frame_w - target_w - pad_x
        y = pad_y
    elif pos == 'bottom_left':
        x = pad_x
        y = frame_h - target_h - pad_y
    elif pos == 'top_center':
        x = (frame_w - target_w) // 2
        y = pad_y
    elif pos == 'bottom_center':
        x = (frame_w - target_w) // 2
        y = frame_h - target_h - pad_y
    else:  # default bottom_right
        x = frame_w - target_w - pad_x
        y = frame_h - target_h - pad_y

    x = max(0, min(frame_w - target_w, x))
    y = max(0, min(frame_h - target_h, y))
    if x % 2 != 0:
        x -= 1
    if y % 2 != 0:
        y -= 1

    return target_w, target_h, x, y


def extract_or_get_watermark(
    ident_clip_path: str | None = None,
    output_png_path: str | None = None,
    timestamp: float = 3.8,
) -> str:
    """Ensure a high-quality watermark PNG exists and return its path.

    If output_png_path or DEFAULT_WATERMARK_ASSET_PATH already exists, returns it.
    Otherwise, extracts a single representative frame from ident_clip_path at
    timestamp (near the end of the 6s animation where the 3D logo is fully resolved),
    crops to the logo bounding box, removes the bright gradient background via
    alpha matting, adds a subtle white rim glow for contrast against dark scenes,
    and saves to PNG.
    """
    target_path = output_png_path or DEFAULT_WATERMARK_ASSET_PATH
    if os.path.isfile(target_path) and os.path.getsize(target_path) > 0:
        return target_path

    ident_path = ident_clip_path or DEFAULT_IDENT_ASSET_PATH
    if not os.path.isfile(ident_path):
        raise FileNotFoundError(
            f"Cannot extract watermark: ident asset not found at {ident_path}"
        )

    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    temp_frame = target_path + f".raw_{uuid.uuid4().hex}.png"
    try:
        extract_cmd = [
            FFMPEG_PATH, '-y', '-nostdin', '-hide_banner',
            '-ss', f"{timestamp:.2f}",
            '-i', ident_path,
            '-vframes', '1',
            temp_frame
        ]
        res = _run_media_command(extract_cmd, timeout=30)
        if res.returncode != 0 or not os.path.isfile(temp_frame):
            raise RuntimeError(f"Failed to extract frame from ident clip: {res.stderr}")

        from PIL import Image, ImageFilter
        import numpy as np
        from collections import deque

        im = Image.open(temp_frame).convert('RGB')
        arr = np.array(im)

        sub = arr[200:900, 400:1500]
        is_dark = np.mean(sub, axis=2) < 185
        ys, xs = np.where(is_dark)
        if len(xs) > 0 and len(ys) > 0:
            ymin, ymax = 200 + ys.min(), 200 + ys.max()
            xmin, xmax = 400 + xs.min(), 400 + xs.max()
            pad = 20
            ymin = max(0, ymin - pad)
            ymax = min(arr.shape[0], ymax + pad)
            xmin = max(0, xmin - pad)
            xmax = min(arr.shape[1], xmax + pad)
            crop = im.crop((xmin, ymin, xmax, ymax))
        else:
            crop = im

        crop_arr = np.array(crop)
        ch, cw, _ = crop_arr.shape

        tl = crop_arr[0, 0].astype(float)
        is_bg = np.all(crop_arr > 185, axis=2) | (np.linalg.norm(crop_arr.astype(float) - tl, axis=2) < 45)

        visited = np.zeros((ch, cw), dtype=bool)
        queue = deque()
        for x in range(cw):
            if is_bg[0, x]: queue.append((0, x)); visited[0, x] = True
            if is_bg[ch-1, x]: queue.append((ch-1, x)); visited[ch-1, x] = True
        for y in range(ch):
            if is_bg[y, 0]: queue.append((y, 0)); visited[y, 0] = True
            if is_bg[y, cw-1]: queue.append((y, cw-1)); visited[y, cw-1] = True

        while queue:
            y, x = queue.popleft()
            for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:
                ny, nx = y + dy, x + dx
                if 0 <= ny < ch and 0 <= nx < cw and not visited[ny, nx] and is_bg[ny, nx]:
                    visited[ny, nx] = True
                    queue.append((ny, nx))

        alpha = np.full((ch, cw), 255, dtype=np.uint8)
        alpha[visited] = 0

        rgba = np.dstack([crop_arr, alpha])
        wm_img = Image.fromarray(rgba, 'RGBA')

        a_mask = Image.fromarray(alpha, 'L')
        outline_mask = a_mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
        glow = Image.new('RGBA', wm_img.size, (255, 255, 255, 0))
        glow.putalpha(outline_mask)

        final_wm = Image.alpha_composite(glow, wm_img)
        final_wm.save(target_path)
        return target_path
    finally:
        _safe_remove_file(temp_frame)


def add_text_overlays_ffmpeg(output_file: str, start_text: str = '',
                              start_position: str = 'bottom_center', start_duration: float = 3.0,
                              end_text: str = '', end_position: str = 'bottom_center',
                              end_duration: float = 3.0, use_nvenc: bool = False,
                              gpu_encoder: str = 'h264_nvenc', fps: float = 30.0,
                              font_file: str | None = None,
                              fade_in: float = 0.0, fade_out: float = 0.0,
                              title_card_enabled: bool = False,
                              title_theme: str | None = None,
                              theme_preset: Optional[Any] = None,
                              watermark_enabled: bool = False,
                              watermark_image: str | None = None,
                              watermark_position: str = 'bottom_right',
                              watermark_opacity: float = 0.60) -> str:
    """Burn optional start/end titles, watermark, and/or a black fade in/out into an assembled video.

    If title_card_enabled is True and start_text is non-empty, applies a blur-to-sharp
    title card opening that smoothly resolves into the sharp first clip footage,
    using the chosen visual theme (typography, color grade, and graphic overlay).
    Otherwise, burns standard text overlay(s).
    If watermark_enabled is True, composites a persistent semi-transparent watermark logo mark
    in the chosen corner (default bottom-right) across the main video.
    """
    start_clean = str(start_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    end_clean = str(end_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    have_text = bool(start_clean or end_clean)
    fade_in = max(0.0, float(fade_in or 0.0))
    fade_out = max(0.0, float(fade_out or 0.0))
    if not have_text and fade_in <= 0.0 and fade_out <= 0.0 and not watermark_enabled:
        return output_file

    if theme_preset is None and (title_theme or title_card_enabled) and resolve_theme:
        theme_preset, _ = resolve_theme(title_theme)

    video_duration = get_video_duration(output_file)
    frame_w, frame_h = get_video_resolution(output_file)
    # Keep the two fades inside the clip and non-overlapping.
    fade_in = min(fade_in, max(0.0, video_duration))
    fade_out = min(fade_out, max(0.0, video_duration - fade_in))

    if not font_file or not os.path.isfile(font_file):
        font_file = DEFAULT_TEXT_FONT_FILE
    font_arg = _escape_drawtext_fontfile(font_file)
    text_base = os.path.splitext(output_file)[0]
    temp_text_files: list[str] = []

    wm_png_path = None
    target_w, target_h, wm_x, wm_y = 0, 0, 0, 0
    if watermark_enabled:
        candidate_wm = watermark_image or get_watermark_asset_path()
        if os.path.isfile(candidate_wm) and os.path.getsize(candidate_wm) > 0:
            wm_png_path = candidate_wm
        else:
            try:
                wm_png_path = extract_or_get_watermark(output_png_path=candidate_wm)
            except Exception as e:
                print(f"   ⚠️ Could not load/extract watermark: {e}")
                wm_png_path = None

        if wm_png_path and os.path.isfile(wm_png_path):
            try:
                from PIL import Image
                with Image.open(wm_png_path) as im:
                    wm_w_raw, wm_h_raw = im.size
            except Exception:
                wm_w_raw, wm_h_raw = 889, 676
            target_w, target_h, wm_x, wm_y = compute_watermark_layout(
                frame_w, frame_h, wm_w_raw, wm_h_raw, position=watermark_position
            )
        else:
            watermark_enabled = False

    use_title_card = bool(title_card_enabled and start_clean)

    def _make_text_filter(text: str, position: str, visible_from: float, visible_to: float,
                           alpha_expr: str | None = None,
                           custom_font: str | None = None,
                           custom_color: str | None = None) -> str:
        x, y = _TEXT_POSITIONS.get(position, _TEXT_POSITIONS['bottom_center'])
        font_size = _title_font_size(text, frame_w, frame_h)
        border_w = max(2, round(font_size / 18))
        line_spacing = max(4, round(font_size / 10))
        target_font = custom_font if (custom_font and os.path.isfile(custom_font)) else font_file
        target_farg = _escape_drawtext_fontfile(target_font)
        color = custom_color or "white"
        if alpha_expr:
            common = (
                f":fontcolor={color}:fontsize={font_size}:borderw={border_w}:bordercolor=black:"
                f"line_spacing={line_spacing}:x={x}:y={y}:"
                f"alpha='{alpha_expr}':expansion=none"
            )
        else:
            common = (
                f":fontcolor={color}:fontsize={font_size}:borderw={border_w}:bordercolor=black:"
                f"line_spacing={line_spacing}:x={x}:y={y}:"
                f"enable='between(t,{visible_from:.3f},{visible_to:.3f})':expansion=none"
            )
        try:
            tf = f"{text_base}_txt_{uuid.uuid4().hex}.txt"
            with open(tf, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(text)
            temp_text_files.append(tf)
            return f"drawtext=fontfile='{target_farg}':textfile='{_escape_drawtext_fontfile(tf)}'{common}"
        except OSError:
            flat = _escape_drawtext_value(text.replace('\n', ' '))
            return f"drawtext=fontfile='{target_farg}':text='{flat}'{common}"

    def _make_custom_text_filter(text: str, f_path: str, f_size: int, f_color: str,
                                 x_expr: str, y_expr: str, visible_from: float, visible_to: float,
                                 alpha_expr: str | None = None) -> str:
        border_w = max(2, round(f_size / 20))
        target_font = f_path if (f_path and os.path.isfile(f_path)) else font_file
        f_arg = _escape_drawtext_fontfile(target_font)
        if alpha_expr:
            common = (
                f":fontcolor={f_color}:fontsize={f_size}:borderw={border_w}:bordercolor=black:"
                f"x={x_expr}:y={y_expr}:alpha='{alpha_expr}':expansion=none"
            )
        else:
            common = (
                f":fontcolor={f_color}:fontsize={f_size}:borderw={border_w}:bordercolor=black:"
                f"x={x_expr}:y={y_expr}:enable='between(t,{visible_from:.3f},{visible_to:.3f})':expansion=none"
            )
        try:
            tf = f"{text_base}_txt_{uuid.uuid4().hex}.txt"
            with open(tf, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(text)
            temp_text_files.append(tf)
            return f"drawtext=fontfile='{f_arg}':textfile='{_escape_drawtext_fontfile(tf)}'{common}"
        except OSError:
            flat = _escape_drawtext_value(text)
            return f"drawtext=fontfile='{f_arg}':text='{flat}'{common}"

    audio_filters = []
    if fade_in > 0.0:
        audio_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0.0:
        fade_out_start = max(0.0, video_duration - fade_out)
        audio_filters.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")

    start_duration = max(0.0, float(start_duration or 0.0))
    end_duration = max(0.0, float(end_duration or 0.0))
    motif_png_path = None
    window = 0.0

    if use_title_card:
        # Blur-to-sharp title treatment with designed typography and theme styling
        window = min(float(start_duration or 2.5), float(video_duration))
        window = max(0.8, window)
        t_hold = round(min(1.2, window * 0.45), 3)
        t_fade = round(window - t_hold, 3)

        title_alpha = f"if(lte(t,{t_hold:.3f}),1.0,if(gte(t,{window:.3f}),0.0,({window:.3f}-t)/{t_fade:.3f}))"

        # Typography: handle multi-line title/subtitle split
        start_lines = [ln.strip() for ln in start_clean.splitlines() if ln.strip()]
        has_subtitle = len(start_lines) >= 2
        title_text = start_lines[0] if start_lines else ""
        subtitle_text = start_lines[1] if has_subtitle else ""

        is_default_font = (font_file is None or font_file == DEFAULT_TEXT_FONT_FILE)
        t_font = (theme_preset.title_font if (theme_preset and hasattr(theme_preset, 'title_font') and is_default_font) else font_file)
        s_font = (theme_preset.subtitle_font if (theme_preset and hasattr(theme_preset, 'subtitle_font') and is_default_font) else font_file)
        t_color = theme_preset.title_color if (theme_preset and hasattr(theme_preset, 'title_color')) else "white"
        s_color = theme_preset.subtitle_color if (theme_preset and hasattr(theme_preset, 'subtitle_color')) else "white"

        if theme_preset:
            try:
                from title_theme import _compute_text_layout
                _, t_size, s_size, l_gap, _, _ = _compute_text_layout(
                    theme_preset, frame_w, frame_h, title_text if has_subtitle else start_clean, subtitle_text
                )
                title_font_size = t_size
                sub_font_size = s_size
                gap = l_gap
                total_block_h = title_font_size + gap + sub_font_size if has_subtitle else title_font_size
            except Exception:
                title_font_size = _title_font_size(title_text if has_subtitle else start_clean, frame_w, frame_h)
                sub_font_size = max(16, int(round(title_font_size * 0.52)))
                gap = max(10, int(round(sub_font_size * 0.55)))
                total_block_h = title_font_size + gap + sub_font_size if has_subtitle else title_font_size
        else:
            title_font_size = _title_font_size(title_text if has_subtitle else start_clean, frame_w, frame_h)
            sub_font_size = max(16, int(round(title_font_size * 0.52)))
            gap = max(10, int(round(sub_font_size * 0.55)))
            total_block_h = title_font_size + gap + sub_font_size if has_subtitle else title_font_size

        if has_subtitle:
            title_y = f"(h-{total_block_h})/2"
            sub_y = f"(h-{total_block_h})/2+{title_font_size}+{gap}"
            title_x = "(w-text_w)/2"
            sub_x = "(w-text_w)/2"

            t_filter = _make_custom_text_filter(title_text, t_font, title_font_size, t_color, title_x, title_y, 0.0, window, alpha_expr=title_alpha)
            s_filter = _make_custom_text_filter(subtitle_text, s_font, sub_font_size, s_color, sub_x, sub_y, 0.0, window, alpha_expr=title_alpha)
            title_text_chain = f"{t_filter},{s_filter}"
        else:
            title_text_chain = _make_custom_text_filter(start_clean, t_font, title_font_size, t_color, "(w-text_w)/2", "(h-text_h)/2", 0.0, window, alpha_expr=title_alpha)

        # Render designed decorative graphics motif PNG (border brackets, confetti, or chevrons)
        motif_png_path = None
        if theme_preset and getattr(theme_preset, 'decorative_motif_type', None):
            try:
                from title_theme import render_decorative_motif
                motif_file = f"{text_base}_motif_{uuid.uuid4().hex}.png"
                render_decorative_motif(
                    theme_preset,
                    frame_w,
                    frame_h,
                    title_text=title_text if has_subtitle else start_clean,
                    subtitle_text=subtitle_text,
                    output_path=motif_file,
                )
                if os.path.isfile(motif_file):
                    motif_png_path = motif_file
                    temp_text_files.append(motif_file)
            except Exception as e:
                print(f"   ⚠️ Could not render decorative motif: {e}")
                motif_png_path = None

        color_grade_eq = theme_preset.title_color_grade_eq if (theme_preset and hasattr(theme_preset, 'title_color_grade_eq')) else "brightness=-0.15:contrast=0.90"
        graphic_type = theme_preset.graphic_overlay_type if (theme_preset and hasattr(theme_preset, 'graphic_overlay_type')) else "bokeh_light_leak"

        blur_chain = (
            f"scale=iw/2:ih/2,"
            f"gblur=sigma=16:steps=2,"
            f"eq={color_grade_eq},"
            f"scale={frame_w}:{frame_h}:flags=bilinear"
        )
        blend_expr = (
            f"if(lte(T,{t_hold:.3f}),B,"
            f"if(gte(T,{window:.3f}),A,"
            f"B*(1-(T-{t_hold:.3f})/{t_fade:.3f})+A*((T-{t_hold:.3f})/{t_fade:.3f})))"
        )

        # Themed procedural graphic overlay
        if graphic_type == "bokeh_light_leak":
            graphic_src = (
                f"color=c=black:s={frame_w}x{frame_h}:d={window}:r={fps},"
                f"noise=alls=60:allf=t+u,scale=iw/8:ih/8,gblur=sigma=20:steps=2,"
                f"scale={frame_w}:{frame_h}:flags=bilinear,"
                f"eq=contrast=2.0:brightness=0.05,colorbalance=rs=0.35:gs=0.15:bs=-0.30[graphic]"
            )
            graphic_blend = f"[blurred][graphic]blend=all_mode=screen[themed_bg]"
        elif graphic_type == "light_particles":
            graphic_src = (
                f"color=c=black:s={frame_w}x{frame_h}:d={window}:r={fps},"
                f"noise=alls=85:allf=t+u,scale=iw/4:ih/4,gblur=sigma=8:steps=2,"
                f"scale={frame_w}:{frame_h}:flags=bilinear,"
                f"eq=contrast=2.4:brightness=0.08,colorbalance=rs=0.25:gs=0.15:bs=0.05[graphic]"
            )
            graphic_blend = f"[blurred][graphic]blend=all_mode=screen[themed_bg]"
        elif graphic_type == "light_streaks":
            graphic_src = (
                f"color=c=black:s={frame_w}x{frame_h}:d={window}:r={fps},"
                f"noise=alls=90:allf=t+u,scale=iw:ih/32,gblur=sigma=24:steps=2,"
                f"scale={frame_w}:{frame_h}:flags=bilinear,"
                f"eq=contrast=2.5:brightness=0.10[graphic]"
            )
            graphic_blend = f"[blurred][graphic]blend=all_mode=screen[themed_bg]"
        else:
            graphic_src = None
            graphic_blend = None

        if graphic_src and graphic_blend:
            fc_parts = [
                f"[0:v]split=2[orig][blur_in]",
                f"[blur_in]{blur_chain}[blurred]",
                graphic_src,
                graphic_blend,
                f"[orig][themed_bg]blend=all_expr='{blend_expr}':enable='lte(t,{window:.3f})'[resolved]",
                f"[resolved]{title_text_chain}[v_text]"
            ]
        else:
            fc_parts = [
                f"[0:v]split=2[orig][blur_in]",
                f"[blur_in]{blur_chain}[blurred]",
                f"[orig][blurred]blend=all_expr='{blend_expr}':enable='lte(t,{window:.3f})'[resolved]",
                f"[resolved]{title_text_chain}[v_text]"
            ]

        # Composite decorative motif graphic via overlay with identical timing
        # CRITICAL: Input 0 MUST be the video stream [v_text], Input 1 the motif [motif_fade].
        # When enable='lte(t, window)' evaluates to false, overlay passes through its first
        # declared input [v_text] (which has resolved to sharp orig with alpha=0 text).
        if motif_png_path:
            fc_parts.append(
                f"[1:v]format=rgba,fade=t=out:st={t_hold:.3f}:d={t_fade:.3f}:alpha=1[motif_fade]"
            )
            fc_parts.append(
                f"[v_text][motif_fade]overlay=0:0:enable='lte(t,{window:.3f})'[v_title]"
            )
        else:
            fc_parts.append(f"[v_text]null[v_title]")

        current_v = "v_title"
        if watermark_enabled and wm_png_path:
            wm_idx = 2 if motif_png_path else 1
            fc_parts.append(
                f"[{wm_idx}:v]scale={target_w}:{target_h},format=rgba,colorchannelmixer=aa={watermark_opacity:.2f}[wm_mark]"
            )
            fc_parts.append(
                f"[{current_v}][wm_mark]overlay=x={wm_x}:y={wm_y}:shortest=1[v_wm]"
            )
            current_v = "v_wm"

        post_filters = []
        if fade_in > 0.0:
            post_filters.append(f"fade=t=in:st=0:d={fade_in:.3f}:color=black")
        if end_clean:
            end_visible_from = min(max(0.0, video_duration - end_duration),
                                   max(0.0, video_duration - fade_out))
            post_filters.append(_make_text_filter(end_clean, end_position, end_visible_from, video_duration))
        if fade_out > 0.0:
            fade_out_start = max(0.0, video_duration - fade_out)
            post_filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}:color=black")

        if post_filters:
            fc_parts.append(f"[{current_v}]{','.join(post_filters)}[v_out]")
        else:
            fc_parts.append(f"[{current_v}]null[v_out]")

        filter_complex_str = "; ".join(fc_parts)
        is_complex = True
        desc = "blur-to-sharp title card" + (" + watermark" if watermark_enabled else "")
    else:
        # Standard overlay branch
        overlays = []
        if start_clean:
            start_visible_to = max(min(start_duration, video_duration), fade_in)
            overlays.append(_make_text_filter(start_clean, start_position, 0.0, start_visible_to))
        if end_clean:
            end_visible_from = min(max(0.0, video_duration - end_duration),
                                   max(0.0, video_duration - fade_out))
            overlays.append(_make_text_filter(end_clean, end_position, end_visible_from, video_duration))

        if watermark_enabled and wm_png_path:
            is_complex = True
            fc_parts = []
            if overlays:
                fc_parts.append(f"[0:v]{','.join(overlays)}[v_txt]")
            else:
                fc_parts.append("[0:v]null[v_txt]")

            fc_parts.append(
                f"[1:v]scale={target_w}:{target_h},format=rgba,colorchannelmixer=aa={watermark_opacity:.2f}[wm_mark]"
            )
            fc_parts.append(
                f"[v_txt][wm_mark]overlay=x={wm_x}:y={wm_y}:shortest=1[v_wm]"
            )
            current_v = "v_wm"

            post_filters = []
            if fade_in > 0.0:
                post_filters.append(f"fade=t=in:st=0:d={fade_in:.3f}:color=black")
            if fade_out > 0.0:
                fade_out_start = max(0.0, video_duration - fade_out)
                post_filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}:color=black")

            if post_filters:
                fc_parts.append(f"[{current_v}]{','.join(post_filters)}[v_out]")
            else:
                fc_parts.append(f"[{current_v}]null[v_out]")

            filter_complex_str = "; ".join(fc_parts)
            desc_parts = []
            if overlays:
                desc_parts.append(f"{len(overlays)} text overlay(s)")
            desc_parts.append("watermark")
            desc = " + ".join(desc_parts)
        else:
            video_filters = list(overlays)
            if fade_in > 0.0:
                video_filters.append(f"fade=t=in:st=0:d={fade_in:.3f}:color=black")
            if fade_out > 0.0:
                fade_out_start = max(0.0, video_duration - fade_out)
                video_filters.append(f"fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}:color=black")

            if not video_filters:
                return output_file

            is_complex = False
            desc = f"{len(overlays)} text overlay(s)"

    base, extension = os.path.splitext(output_file)
    temp_output = f"{base}_text_overlay_{uuid.uuid4().hex}{extension}"
    bits = [desc]
    if fade_in > 0.0 or fade_out > 0.0:
        bits.append(f"fade in {fade_in:.2f}s / out {fade_out:.2f}s")
    print(f"   📝 Adding {', '.join(bits)}...")
    cmd = [FFMPEG_PATH, '-nostdin', '-hide_banner', '-i', output_file]
    if is_complex and motif_png_path:
        cmd.extend(['-loop', '1', '-t', f"{window:.3f}", '-i', motif_png_path])
    if is_complex and watermark_enabled and wm_png_path:
        cmd.extend(['-loop', '1', '-i', wm_png_path])
    if is_complex:
        cmd.extend(['-filter_complex', filter_complex_str, '-map', '[v_out]', '-map', '0:a?'])
    else:
        cmd.extend(['-map', '0:v:0', '-map', '0:a?', '-vf', ','.join(video_filters)])
    if output_file.lower().endswith('.mov'):
        cmd.extend(['-c:v', 'prores', '-profile:v', '0', '-vendor', 'apl0', '-pix_fmt', 'yuv422p10le'])
    elif use_nvenc:
        if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
            cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
        elif gpu_encoder in ('h264_amf', 'hevc_amf'):
            cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
    else:
        cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True))
    if audio_filters:
        cmd.extend(['-af', ','.join(audio_filters)])
        cmd.extend(['-c:a', 'pcm_s16le'] if output_file.lower().endswith('.mov')
                   else ['-c:a', 'aac', '-b:a', '320k'])
    else:
        cmd.extend(['-c:a', 'copy'])
    cmd.extend(['-fps_mode', 'cfr', '-r', str(fps), '-movflags', '+faststart', '-y', temp_output])

    try:
        result = _run_media_command(cmd, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Text overlay failed: {_short_ffmpeg_error(result.stderr)}")
        os.replace(temp_output, output_file)
        return output_file
    finally:
        _safe_remove_file(temp_output)
        for tf in temp_text_files:
            _safe_remove_file(tf)


def get_audio_codec_and_rate(file_path: str) -> Tuple[str, int, int]:
    """Return (codec_name, sample_rate, channels) for file_path's primary audio stream."""
    try:
        cmd = [
            FFPROBE_PATH, '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_name,sample_rate,channels',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        res = _run_media_command(cmd, timeout=10)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        if len(lines) >= 3:
            return lines[0], int(lines[1]), int(lines[2])
    except Exception:
        pass
    return ('aac', 48000, 2)


def append_ident_outro(
    main_video_file: str,
    ident_clip_path: str | None = None,
    use_nvenc: bool = False,
    gpu_encoder: str = 'h264_nvenc',
    fps: float = 30.0,
    temp_dir: str | None = None,
) -> str:
    """Scale, re-encode, and append the 3D ident outro clip to the end of main_video_file.

    Scales/letterboxes the ident clip to match the main video's resolution (landscape 4K/1080p
    or vertical 9:16) using build_fit_scale_filter(), re-encodes video matching the main render's
    encoder (AMF/NVENC/CPU/ProRes) and FPS, preserves unmuted stereo audio (matching main audio
    sample format and rate), concatenates via fast stream-copy demuxer (falling back to
    filter-complex concat if needed), and atomically replaces main_video_file.
    """
    ident_path = ident_clip_path or get_ident_asset_path()
    if not os.path.isfile(ident_path):
        print(f"   ⚠️ Ident outro clip not found at {ident_path}; skipping outro append.")
        return main_video_file

    frame_w, frame_h = get_video_resolution(main_video_file)
    main_fps = get_video_fps(main_video_file) or fps
    is_prores = main_video_file.lower().endswith('.mov')

    audio_codec, sample_rate, channels = get_audio_codec_and_rate(main_video_file)

    work_dir = temp_dir or os.path.dirname(os.path.abspath(main_video_file))
    base_name = os.path.splitext(os.path.basename(main_video_file))[0]
    ext = os.path.splitext(main_video_file)[1] or ('.mov' if is_prores else '.mp4')

    transcoded_outro = os.path.join(work_dir, f"{base_name}_ident_transcoded_{uuid.uuid4().hex}{ext}")
    concat_list_file = os.path.join(work_dir, f"{base_name}_concat_list_{uuid.uuid4().hex}.txt")
    temp_merged_file = os.path.join(work_dir, f"{base_name}_with_ident_{uuid.uuid4().hex}{ext}")

    print(f"   🎬 Transcoding ident outro clip to match {frame_w}x{frame_h} @ {main_fps:.2f}fps ({'ProRes' if is_prores else gpu_encoder}, audio: {audio_codec})...")
    scale_filter = build_fit_scale_filter(frame_w, frame_h)

    # 1. Transcode the ident clip
    transcode_cmd = [
        FFMPEG_PATH, '-y', '-nostdin', '-hide_banner',
        '-i', ident_path,
        '-vf', scale_filter,
    ]

    # Video encoding args
    if is_prores:
        transcode_cmd.extend(['-c:v', 'prores', '-profile:v', '0', '-vendor', 'apl0', '-pix_fmt', 'yuv422p10le'])
    elif use_nvenc:
        if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
            transcode_cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
        elif gpu_encoder in ('h264_amf', 'hevc_amf'):
            transcode_cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
        else:
            transcode_cmd.extend(['-c:v', gpu_encoder, '-pix_fmt', 'yuv420p'])
    else:
        transcode_cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True))

    # Audio encoding args: match the main video's audio codec & sample rate
    if is_prores:
        transcode_cmd.extend(['-c:a', 'pcm_s16le', '-ar', str(sample_rate), '-ac', str(channels)])
    elif audio_codec == 'pcm_s24le':
        transcode_cmd.extend(['-c:a', 'pcm_s24le', '-ar', str(sample_rate), '-ac', str(channels)])
    elif audio_codec == 'pcm_s16le':
        transcode_cmd.extend(['-c:a', 'pcm_s16le', '-ar', str(sample_rate), '-ac', str(channels)])
    else:
        transcode_cmd.extend(['-c:a', 'aac', '-b:a', '320k', '-ar', str(sample_rate), '-ac', str(channels)])

    transcode_cmd.extend([
        '-fps_mode', 'cfr', '-r', str(main_fps),
        '-movflags', '+faststart',
        transcoded_outro
    ])

    try:
        t_start = time.perf_counter()
        res = _run_media_command(transcode_cmd, timeout=180)
        if res.returncode != 0 or not os.path.isfile(transcoded_outro):
            raise RuntimeError(f"Failed to transcode ident outro: {_short_ffmpeg_error(res.stderr)}")
        print(f"   ✓ Ident outro transcoded in {_fmt_seconds(time.perf_counter() - t_start)}")

        # 2. Concat via fast stream-copy demuxer
        with open(concat_list_file, 'w', encoding='utf-8') as f:
            m_path = os.path.abspath(main_video_file).replace("'", "'\\''")
            i_path = os.path.abspath(transcoded_outro).replace("'", "'\\''")
            f.write(f"file '{m_path}'\n")
            f.write(f"file '{i_path}'\n")

        print(f"   🔗 Appending ident outro to main video...")
        concat_cmd = [
            FFMPEG_PATH, '-y', '-nostdin', '-hide_banner',
            '-f', 'concat', '-safe', '0',
            '-i', concat_list_file,
            '-c', 'copy',
            '-fflags', '+genpts',
            '-movflags', '+faststart',
            temp_merged_file
        ]
        c_res = _run_media_command(concat_cmd, timeout=120)
        if c_res.returncode == 0 and os.path.isfile(temp_merged_file) and os.path.getsize(temp_merged_file) > 0:
            os.replace(temp_merged_file, main_video_file)
            print(f"   ✓ Ident outro successfully appended to {main_video_file}")
            return main_video_file

        # Fallback to filter-complex concat if stream-copy was rejected
        print(f"   ⚠️ Concat stream-copy failed ({_short_ffmpeg_error(c_res.stderr)}); falling back to filter concat...")
        fallback_cmd = [
            FFMPEG_PATH, '-y', '-nostdin', '-hide_banner',
            '-i', main_video_file,
            '-i', transcoded_outro,
            '-filter_complex', '[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[v][a]',
            '-map', '[v]', '-map', '[a]',
        ]
        if is_prores:
            fallback_cmd.extend(['-c:v', 'prores', '-profile:v', '0', '-vendor', 'apl0', '-pix_fmt', 'yuv422p10le'])
            fallback_cmd.extend(['-c:a', 'pcm_s16le', '-ar', str(sample_rate), '-ac', str(channels)])
        elif use_nvenc:
            if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
                fallback_cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
            elif gpu_encoder in ('h264_amf', 'hevc_amf'):
                fallback_cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
            else:
                fallback_cmd.extend(['-c:v', gpu_encoder, '-pix_fmt', 'yuv420p'])
            fallback_cmd.extend(['-c:a', 'aac', '-b:a', '320k', '-ar', str(sample_rate), '-ac', str(channels)])
        else:
            fallback_cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True))
            fallback_cmd.extend(['-c:a', 'aac', '-b:a', '320k', '-ar', str(sample_rate), '-ac', str(channels)])

        fallback_cmd.extend([
            '-fps_mode', 'cfr', '-r', str(main_fps),
            '-movflags', '+faststart',
            temp_merged_file
        ])
        fb_res = _run_media_command(fallback_cmd, timeout=300)
        if fb_res.returncode != 0 or not os.path.isfile(temp_merged_file):
            raise RuntimeError(f"Ident outro concat fallback failed: {_short_ffmpeg_error(fb_res.stderr)}")

        os.replace(temp_merged_file, main_video_file)
        print(f"   ✓ Ident outro appended via filter concat to {main_video_file}")
        return main_video_file
    finally:
        _safe_remove_file(transcoded_outro)
        _safe_remove_file(concat_list_file)
        _safe_remove_file(temp_merged_file)


def convert_to_prores_proxy(video_file: str, output_dir: str, fps: float = None) -> str:
    """
    Convert video to ProRes 422 Proxy for lossless editing.
    All frames are I-frames (keyframes) for frame-accurate cutting.
    STRIPS AUDIO - we'll add the music track at the end.
    """
    filename = os.path.basename(video_file)
    name, _ = os.path.splitext(filename)
    output_file = os.path.join(output_dir, f"{name}_prores.mov")
    
    print(f"   📹 Converting to ProRes 422 Proxy: {filename}")
    
    # Detect FPS if not provided
    if fps is None:
        fps = get_video_fps(video_file)
    
    # Build FFmpeg command for ProRes 422 Proxy (NO AUDIO).
    # ProRes encode/decode is CPU-native in FFmpeg; forcing hwaccel auto can make
    # FFmpeg pick Vulkan/D3D paths that are slower or unstable for ProRes.
    cmd = [
        FFMPEG_PATH,
        '-nostdin',
        '-hide_banner',
        '-i', video_file,
        '-map', '0:v:0',
        '-c:v', 'prores',  # ProRes encoder
        '-profile:v', '0',  # Proxy quality (0=Proxy, 1=LT, 2=Standard, 3=HQ)
        '-vendor', 'apl0',
        '-pix_fmt', 'yuv422p10le',
        '-an',  # ✅ STRIP AUDIO - we'll add music at the end
        '-sn',
        '-dn',
        '-r', str(fps),  # Set frame rate
        '-threads', str(MAX_THREADS),
        '-y',
        output_file
    ]
    
    try:
        result = _run_media_command(cmd, timeout=600)  # 10 minute timeout
        
        if result.returncode != 0:
            print(f"   ⚠️  FFmpeg error: {result.stderr}")
            raise Exception(f"ProRes conversion failed for {filename}")
        
        print(f"   ✓ ProRes conversion complete: {name}_prores.mov (video only, no audio)")
        return output_file
        
    except subprocess.TimeoutExpired:
        raise Exception(f"ProRes conversion timeout for {filename}")
    except Exception as e:
        raise Exception(f"ProRes conversion error: {str(e)}")


def extract_clip_segment_ffmpeg(video_file: str, start_time: float, duration: float,
                                output_file: str, fps: float, target_size: Tuple[int, int],
                                use_nvenc: bool,
                                gpu_encoder: str = 'h264_nvenc',
                                threads: int | None = None,
                                hwaccel: bool = True,
                                low_priority: bool = False,
                                subject_bbox: Tuple[float, float, float, float] | None = None,
                                initial_crop_x: int | None = None,
                                transition_duration: float | None = None,
                                skip_ease: bool = False) -> bool:
    """
    Extract a video segment using FFmpeg with FRAME-ACCURATE timing.
    
    ✅ FRAME-ACCURATE: Uses exact frame counts instead of floating-point seconds
    ✅ ZERO DRIFT: No cumulative timing errors
    """
    try:
        # ✅ FRAME-ACCURATE: Calculate exact source and output frame counts.
        source_frame_count = max(1, seconds_to_frame_count(duration, fps))
        exact_source_duration = frame_count_to_seconds(source_frame_count, fps)
        output_frame_count = source_frame_count

        # Build filter complex
        filters = []

        # Trim first so each extracted segment has exact timing.
        filters.extend([f"trim=duration={exact_source_duration}", "setpts=PTS-STARTPTS"])
        
        # Scale to target size. For vertical mode (height > width), use smart crop-to-fill
        # centered on the detected subject bbox. For landscape, letterbox/fit as usual.
        if target_size:
            width, height = target_size
            if height > width:
                src_w, src_h = get_video_resolution(video_file)
                filters.append(build_crop_to_fill_filter(
                    src_w, src_h, width, height, subject_bbox,
                    clip_duration=exact_source_duration,
                    initial_crop_x=initial_crop_x,
                    transition_duration=transition_duration,
                    skip_ease=skip_ease,
                ))
            else:
                filters.append(build_fit_scale_filter(width, height))
        
        # FPS filter with clone-mode edge padding for frame guarantee
        filters.append("tpad=start_mode=clone:stop_mode=clone")
        filters.append(f"fps={fps}")
        
        filter_complex = ",".join(filters)
        
        # Build FFmpeg command
        cmd = [FFMPEG_PATH]
        
        # Hardware acceleration. CUDA decode hwaccel is NVIDIA-specific, so gate it on
        # the NVENC family specifically. Do NOT use '-hwaccel auto' for anything else
        # (CPU or AMF) -- confirmed on real hardware that FFmpeg's 'auto' selection can
        # pick DXVA2 and fail with "Failed to create Direct3D device" on at least one
        # real Windows/AMD-iGPU machine (same class of driver-combination failure the
        # ProRes path above already documents/avoids). Only the encode is meant to be
        # hardware-accelerated for AMF; decode falls back to plain CPU/software, same
        # as it always has for the CPU-only path.
        if use_nvenc and gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
            cmd.extend(['-hwaccel', 'cuda'])
        
        # ✅ FRAME-ACCURATE INPUT SEEKING
        # Use -ss BEFORE -i for faster seeking (keyframe-based)
        # Then use -ss AFTER -i for frame-accurate positioning
        cmd.extend([
            '-ss', str(start_time),
            '-t', str(exact_source_duration),
            '-i', video_file
        ])
        
        # Video filters
        cmd.extend(['-vf', filter_complex])
        
        # ✅ FRAME-ACCURATE DURATION: Use -vframes instead of -t
        cmd.extend(['-vframes', str(output_frame_count)])
        
        # Video encoding
        if use_nvenc:
            if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
                cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
            elif gpu_encoder in ('h264_amf', 'hevc_amf'):
                cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
        else:
            cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True, threads=threads))
        
        # No audio, frame-accurate settings
        cmd.extend([
            '-an',
            '-fps_mode', 'cfr',  # Constant frame rate
            '-r', str(fps),   # Exact output FPS
            '-fflags', '+genpts',
            '-movflags', '+faststart',
            '-y',
            output_file
        ])
        
        result = _run_media_command(cmd, timeout=120, low_priority=low_priority)
        
        if result.returncode != 0:
            print(f"   ⚠️  FFmpeg error: {result.stderr}")
            return False
        
        # Verify output exists and has content
        if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
            return False
        
        return True
        
    except Exception as e:
        print(f"   ⚠️  Error extracting clip: {e}")
        return False


def extract_prores_segment_random(video_file: str, duration: float, fps: float,
                                  temp_dir: str, segment_index: int,
                                  start_time: float = None) -> str:
    """
    Extract a segment from a ProRes proxy with frame-perfect precision.

    Important stability fix:
    - Do NOT use '-hwaccel auto' here. FFmpeg can select Vulkan/D3D hwaccel for
      ProRes, which is unnecessary for ProRes and can fail on some Windows GPU
      driver combinations.
    - Use a CPU-native ProRes path, exact frame count, and a safe retry command.
    """
    output_file = os.path.join(temp_dir, f"segment_{segment_index:05d}.mov")

    video_duration = get_video_duration(video_file)
    if video_duration <= 0:
        raise Exception(f"Invalid ProRes source duration: {video_file}")

    if video_duration >= duration:
        max_start = max(0.0, video_duration - duration)
        if start_time is None:
            start_time = random.uniform(0.0, max_start)
        else:
            start_time = max(0.0, min(float(start_time), max_start))
    else:
        start_time = 0.0
        duration = video_duration

    frame_count = max(1, seconds_to_frame_count(duration, fps))
    exact_duration = frame_count_to_seconds(frame_count, fps)

    filters = [f"trim=duration={exact_duration}", "setpts=PTS-STARTPTS"]
    filters.append(f"fps={fps}")
    filter_complex = ",".join(filters)

    def build_cmd(fast_seek: bool) -> List[str]:
        cmd = [FFMPEG_PATH, '-nostdin', '-hide_banner']
        if fast_seek:
            # ProRes proxy is intra-frame, so input-side seeking remains accurate
            # while being much faster for long sources.
            cmd.extend(['-ss', f'{start_time:.6f}', '-i', video_file])
        else:
            # Ultra-safe fallback. Slower on long sources, but avoids muxer/seek
            # edge cases if a specific FFmpeg build rejects the fast path.
            cmd.extend(['-i', video_file, '-ss', f'{start_time:.6f}'])

        cmd.extend([
            '-map', '0:v:0',
            '-vf', filter_complex,
            '-vframes', str(frame_count),
            '-c:v', 'prores',
            '-profile:v', '0',
            '-vendor', 'apl0',
            '-pix_fmt', 'yuv422p10le',
            '-r', str(fps),
            '-fps_mode', 'cfr',
            '-fflags', '+genpts',
            '-an',
            '-sn',
            '-dn',
            '-threads', str(MAX_THREADS),
            '-y',
            output_file,
        ])
        return cmd

    last_error = ""
    for attempt_name, fast_seek, timeout in [
        ('fast intra-frame seek', True, 180),
        ('safe accurate seek retry', False, 360),
    ]:
        _safe_remove_file(output_file)
        result = _run_media_command(build_cmd(fast_seek), timeout=timeout)
        if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return output_file
        last_error = _short_ffmpeg_error(result.stderr)
        print(f"   ⚠️  ProRes extraction failed on {attempt_name}: {last_error}")

    raise Exception(f"ProRes segment extraction error: {last_error}")


DEFAULT_TRANSITION_DURATION = 0.35


def _build_transition_filtergraph(
    video_files: List[str],
    transitions: Sequence[float | None],
    segment_durations: Sequence[float],
    theme_preset: Optional[Any] = None,
) -> Tuple[List[str], str]:
    """Construct FFmpeg filtergraph inputs and filter_complex string for beat-matched transitions.

    Partitions clips into blocks separated by hard cuts (where transition is None).
    Inside each block, clips are crossfaded using xfade with exact duration and offset.
    If a theme preset is provided with transition_tint_eq, a subtle matching color grade
    shift or flash is applied during each crossfade blend window.
    Blocks are then joined via concat filter, preserving exact beat positions and total duration.
    """
    n = len(video_files)
    t_list = list(transitions) if transitions is not None else []

    # Pre-calculate handles
    in_handles = [0.0] * n
    out_handles = [0.0] * n
    for i in range(1, n):
        t = t_list[i - 1] if i - 1 < len(t_list) else None
        if t and t > 0:
            half = round(t / 2.0, 4)
            out_handles[i - 1] = half
            in_handles[i] = half

    clip_lengths = [
        round(in_handles[i] + float(segment_durations[i]) + out_handles[i], 4)
        for i in range(n)
    ]

    # Partition into blocks separated by hard cuts
    blocks: List[List[int]] = []
    current_block: List[int] = [0]
    for i in range(1, n):
        t = t_list[i - 1] if i - 1 < len(t_list) else None
        if t and t > 0:
            current_block.append(i)
        else:
            blocks.append(current_block)
            current_block = [i]
    blocks.append(current_block)

    theme_tint = theme_preset.transition_tint_eq if (theme_preset and hasattr(theme_preset, 'transition_tint_eq')) else None
    xfade_trans = theme_preset.xfade_transition if (theme_preset and hasattr(theme_preset, 'xfade_transition')) else "fade"

    filter_chains = []
    for b_idx, block in enumerate(blocks):
        if len(block) == 1:
            c = block[0]
            filter_chains.append(f"[{c}:v]null[b{b_idx}]")
        else:
            c0 = block[0]
            curr_dur = clip_lengths[c0]
            prev_stream = f"[{c0}:v]"
            for j in range(1, len(block)):
                cj = block[j]
                d = float(t_list[cj - 1])
                offset = max(0.0, round(curr_dur - d, 4))
                if theme_tint:
                    xf_raw = f"[xf_raw_{b_idx}_{j}]"
                    next_stream = f"[b{b_idx}]" if j == len(block) - 1 else f"[xf_{b_idx}_{j}]"
                    filter_chains.append(
                        f"{prev_stream}[{cj}:v]xfade=transition={xfade_trans}:duration={d:.3f}:offset={offset:.4f}{xf_raw}"
                    )
                    filter_chains.append(
                        f"{xf_raw}eq={theme_tint}:enable='between(t,{offset:.4f},{offset+d:.4f})'{next_stream}"
                    )
                else:
                    next_stream = f"[b{b_idx}]" if j == len(block) - 1 else f"[xf_{b_idx}_{j}]"
                    filter_chains.append(
                        f"{prev_stream}[{cj}:v]xfade=transition={xfade_trans}:duration={d:.3f}:offset={offset:.4f}{next_stream}"
                    )
                prev_stream = next_stream
                curr_dur = round(curr_dur + clip_lengths[cj] - d, 4)

    if len(blocks) == 1:
        filter_chains.append("[b0]null[outv]")
    else:
        concat_inputs = "".join(f"[b{b_idx}]" for b_idx in range(len(blocks)))
        filter_chains.append(f"{concat_inputs}concat=n={len(blocks)}:v=1:a=0[outv]")

    input_args: List[str] = []
    for vf in video_files:
        input_args.extend(['-i', vf])

    return input_args, "; ".join(filter_chains)


def concatenate_videos_ffmpeg(video_files: List[str], output_file: str, 
                              audio_file: str = None, start_time: float = 0.0,
                              end_time: float = None, use_nvenc: bool = False,
                              gpu_encoder: str = 'h264_nvenc', fps: float = 30.0,
                              temp_dir: str = None,
                              transitions: Sequence[float | None] | None = None,
                              segment_durations: Sequence[float] | None = None,
                              title_theme: str | None = None,
                              theme_preset: Optional[Any] = None) -> str:
    """
    Concatenate video files using FFmpeg.
    If transitions are supplied and contain active crossfades, assembles via xfade + concat,
    applying any visual theme transition styling.
    Otherwise uses the fast stream-copy concat demuxer.
    
    ✅ FRAME-ACCURATE: Maintains precise timing through concatenation
    """
    if temp_dir is None:
        temp_dir = os.path.dirname(output_file)

    if theme_preset is None and title_theme and resolve_theme:
        theme_preset, _ = resolve_theme(title_theme)

    has_transitions = bool(
        transitions is not None
        and len(transitions) > 0
        and any(t is not None and t > 0 for t in transitions)
        and segment_durations is not None
        and len(segment_durations) == len(video_files)
    )

    is_prores = output_file.lower().endswith('.mov')

    if has_transitions:
        input_args, filter_complex = _build_transition_filtergraph(
            video_files, transitions, segment_durations, theme_preset=theme_preset
        )
        fade_count = sum(1 for t in transitions if t and t > 0)
        cut_count = sum(1 for t in transitions if t is None or t <= 0)
        print(f"   🔀 Assembling {len(video_files)} segments ({fade_count} crossfade(s), {cut_count} hard cut(s))...")
        assemble_started = time.perf_counter()
        cmd = [FFMPEG_PATH, '-nostdin', '-hide_banner']
        cmd.extend(input_args)
        audio_idx = len(video_files)
        if audio_file:
            if end_time and end_time > start_time:
                cmd.extend(['-ss', str(start_time), '-t', str(end_time - start_time), '-i', audio_file])
            elif start_time > 0:
                cmd.extend(['-ss', str(start_time), '-i', audio_file])
            else:
                cmd.extend(['-i', audio_file])

        cmd.extend(['-filter_complex', filter_complex])
        cmd.extend(['-map', '[outv]'])
        if audio_file:
            cmd.extend(['-map', f'{audio_idx}:a:0'])

        if is_prores:
            cmd.extend(['-c:v', 'prores', '-profile:v', '0', '-pix_fmt', 'yuv422p10le'])
            if audio_file:
                cmd.extend(['-c:a', 'pcm_s24le', '-ar', '48000', '-shortest'])
        else:
            if use_nvenc:
                if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
                    cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
                elif gpu_encoder in ('h264_amf', 'hevc_amf'):
                    cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
            else:
                cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True))

            if audio_file:
                cmd.extend(['-c:a', 'pcm_s24le', '-ar', '48000', '-shortest'])
            cmd.extend(['-fflags', '+genpts', '-movflags', '+faststart'])

        cmd.extend(['-fps_mode', 'cfr', '-r', str(fps), '-y', output_file])

        result = _run_media_command(cmd, timeout=600)
        if result.returncode != 0:
            raise Exception(f"Transition assembly failed: {result.stderr}")
        print(f"   ✓ Transition assembly complete in {_fmt_seconds(time.perf_counter() - assemble_started)}")
        return output_file

    # Create concat file
    concat_file = os.path.join(temp_dir, f'concat_list_{uuid.uuid4().hex}.txt')
    with open(concat_file, 'w', encoding='utf-8') as f:
        for video_file in video_files:
            escaped_path = video_file.replace('\\', '/')
            f.write(f"file '{escaped_path}'\n")

    temp_video = None
    temp_audio = None
    
    try:
        if is_prores:
            # ProRes: concat with stream copy (lossless)
            print(f"   🔗 Concatenating {len(video_files)} segments (lossless stream copy)...")
            
            temp_video = os.path.join(temp_dir, f'video_only_{uuid.uuid4().hex}.mov')
            
            cmd = [
                FFMPEG_PATH,
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                '-y',
                temp_video
            ]
            
            result = _run_media_command(cmd, timeout=300)
            
            if result.returncode != 0:
                raise Exception(f"Concatenation failed: {result.stderr}")
            
            # Add audio if provided
            if audio_file:
                print(f"   🎵 Adding music track...")
                
                temp_audio = os.path.join(temp_dir, f'music_{uuid.uuid4().hex}.wav')
                
                audio_cmd = [FFMPEG_PATH, '-i', audio_file]
                
                if end_time and end_time > start_time:
                    audio_cmd.extend(['-ss', str(start_time), '-t', str(end_time - start_time)])
                elif start_time > 0:
                    audio_cmd.extend(['-ss', str(start_time)])
                
                audio_cmd.extend([
                    '-acodec', 'pcm_s24le',
                    '-ar', '48000',
                    '-ac', '2',
                    '-y',
                    temp_audio
                ])
                
                result = _run_media_command(audio_cmd, timeout=120)
                
                if result.returncode != 0:
                    raise Exception(f"Audio extraction failed: {result.stderr}")
                
                # Combine video + audio with AUDIO as master timeline
                cmd = [
                    FFMPEG_PATH,
                    '-i', temp_video,
                    '-i', temp_audio,
                    '-map', '0:v',
                    '-map', '1:a',
                    '-c:v', 'copy',
                    '-c:a', 'pcm_s24le',
                    '-ar', '48000',
                    '-shortest',  # Use shortest stream (audio)
                    '-y',
                    output_file
                ]
                
                result = _run_media_command(cmd, timeout=300)
                
                if result.returncode != 0:
                    raise Exception(f"Audio merging failed: {result.stderr}")
                
                _safe_remove_file(temp_video)
                _safe_remove_file(temp_audio)
            else:
                shutil.move(temp_video, output_file)
        
        else:
            # H.264/H.265 standard path. Temp clips were already encoded with
            # matching FPS/resolution/codec settings, so the fastest safe path is
            # stream-copy concatenation plus audio mux. If a specific codec/container
            # combination rejects stream copy, fall back to the old re-encode path.
            fast_concat_enabled = _env_flag('BEATSYNC_FAST_CONCAT_COPY', True)

            def add_audio_input(cmd: List[str]) -> None:
                if not audio_file:
                    return
                if end_time and end_time > start_time:
                    cmd.extend(['-ss', str(start_time), '-t', str(end_time - start_time), '-i', audio_file])
                elif start_time > 0:
                    cmd.extend(['-ss', str(start_time), '-i', audio_file])
                else:
                    cmd.extend(['-i', audio_file])

            if fast_concat_enabled:
                print(f"   🔗 Fast final assembly: concat stream-copy video + mux audio...")
                copy_started = time.perf_counter()
                cmd = [
                    FFMPEG_PATH,
                    '-nostdin',
                    '-hide_banner',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file,
                ]
                add_audio_input(cmd)
                if audio_file:
                    cmd.extend(['-map', '0:v:0', '-map', '1:a:0'])
                else:
                    cmd.extend(['-map', '0:v:0'])
                cmd.extend(['-c:v', 'copy'])
                if audio_file:
                    cmd.extend(['-c:a', 'pcm_s24le', '-ar', '48000', '-shortest'])
                cmd.extend(['-fflags', '+genpts', '-movflags', '+faststart', '-y', output_file])

                result = _run_media_command(cmd, timeout=300)
                if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                    print(f"   ✓ Fast concat-copy complete in {_fmt_seconds(time.perf_counter() - copy_started)}")
                    return output_file
                print(
                    f"   ⚠️  Fast concat-copy failed in {_fmt_seconds(time.perf_counter() - copy_started)}; "
                    f"falling back to re-encode. {_short_ffmpeg_error(result.stderr, 900)}"
                )

            # Fallback/original behavior: H.264/H.265 full re-encode.
            print(f"   🔗 Concatenating and encoding {len(video_files)} segments...")
            encode_started = time.perf_counter()
            cmd = [FFMPEG_PATH]
            
            # CUDA decode hwaccel is NVIDIA-specific. Do NOT fall back to '-hwaccel auto'
            # for CPU/AMF -- confirmed on real hardware it can pick DXVA2 and fail with
            # "Failed to create Direct3D device" (same driver-combination risk the ProRes
            # path already documents). Decode falls back to plain CPU/software instead.
            if use_nvenc and gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
                cmd.extend(['-hwaccel', 'cuda'])

            cmd.extend([
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_file
            ])

            add_audio_input(cmd)
            if audio_file:
                cmd.extend(['-map', '0:v', '-map', '1:a'])

            if use_nvenc:
                if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
                    cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
                elif gpu_encoder in ('h264_amf', 'hevc_amf'):
                    cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
            else:
                cmd.extend(get_cpu_h264_quality_args(include_pix_fmt=True))
            
            if audio_file:
                cmd.extend([
                    '-c:a', 'pcm_s24le',
                    '-ar', '48000',
                    '-shortest',
                ])
            
            cmd.extend([
                '-fps_mode', 'cfr',
                '-r', str(fps),
                '-y',
                output_file
            ])
            
            result = _run_media_command(cmd, timeout=600)
            
            if result.returncode != 0:
                raise Exception(f"Encoding failed: {result.stderr}")
            print(f"   ✓ Full final re-encode complete in {_fmt_seconds(time.perf_counter() - encode_started)}")
        
        return output_file
    finally:
        _safe_remove_file(concat_file)
        _safe_remove_file(temp_audio)
        _safe_remove_file(temp_video)


def detect_video_scene_changes(video_path: str, threshold: float = 0.28,
                               use_gpu: bool = False,
                               analysis_fps: float = 8.0,
                               analysis_width: int = 384) -> List[float]:
    """
    Detect likely montage/scene changes using FFmpeg's scene score.

    GPU note:
    FFmpeg's `scene` comparison itself is a CPU video filter, but when GPU mode
    is enabled this uses CUDA decode + CUDA resize, then downloads a small
    analysis frame for the CPU scene score. That makes the expensive decode/scale
    stage GPU-assisted while preserving the same semantic scene-cut signal.
    If CUDA decode is unsupported for a source codec, it automatically falls
    back to the CPU analysis path.
    """
    try:
        print(f"   🎬 Analyzing scene changes: {os.path.basename(video_path)}")
        print(f"   Threshold: {threshold}")
        print(f"   Analysis: {analysis_fps:g} fps @ {analysis_width}px wide")

        filter_cpu = (
            f"fps={analysis_fps},"
            f"scale={analysis_width}:-2:flags=fast_bilinear,"
            f"select='gt(scene,{threshold})',showinfo"
        )
        filter_gpu = (
            f"scale_cuda={analysis_width}:-2,"
            f"hwdownload,format=nv12,"
            f"fps={analysis_fps},"
            f"select='gt(scene,{threshold})',showinfo"
        )

        commands = []
        if use_gpu:
            commands.append((
                'GPU-assisted CUDA decode/scale',
                [
                    FFMPEG_PATH,
                    '-nostdin',
                    '-hide_banner',
                    '-hwaccel', 'cuda',
                    '-hwaccel_output_format', 'cuda',
                    '-i', video_path,
                    '-vf', filter_gpu,
                    '-an', '-sn', '-dn',
                    '-f', 'null',
                    '-'
                ],
            ))

        commands.append((
            'CPU fast scene score',
            [
                FFMPEG_PATH,
                '-nostdin',
                '-hide_banner',
                '-threads', str(MAX_THREADS),
                '-i', video_path,
                '-vf', filter_cpu,
                '-an', '-sn', '-dn',
                '-f', 'null',
                '-'
            ],
        ))

        last_error = ''
        for label, cmd in commands:
            if label.startswith('GPU'):
                print("   ⚡ GPU scene analysis: CUDA decode/scale + CPU scene score")
            else:
                if use_gpu:
                    print("   ↪ GPU scene analysis unavailable/failed, using CPU fallback")
                else:
                    print("   💻 CPU scene analysis")

            command_started = time.perf_counter()
            result = _run_media_command(cmd, timeout=300)
            command_elapsed = time.perf_counter() - command_started
            if result.returncode == 0:
                cleaned = _extract_scene_times(result.stderr)
                print(
                    f"   ✓ Found {len(cleaned)} visual scene changes ({label}) "
                    f"in {command_elapsed:.1f}s"
                )
                return cleaned

            print(f"   ⚠️  Scene command failed after {command_elapsed:.1f}s ({label})")
            last_error = _short_ffmpeg_error(result.stderr, max_chars=1200)
            if label.startswith('GPU'):
                print(f"   ⚠️  GPU scene analysis failed, fallback enabled: {last_error}")

        print(f"   ⚠️  Warning: Scene detection failed: {last_error}")
        return []

    except subprocess.TimeoutExpired:
        print(f"   ⚠️  Warning: Scene detection timeout")
        return []
    except Exception as e:
        print(f"   ⚠️  Warning: Could not analyze scene changes: {e}")
        return []

def detect_video_keyframes(video_path: str, min_interval: float = 0.20) -> List[float]:
    """
    Detect codec keyframes/I-frames with ffprobe.

    Keyframes are not always creative scene cuts, but they are useful as a
    fallback signal for footage that was encoded with keyframes at montage cuts.
    """
    try:
        print(f"   🔑 Reading codec keyframes: {os.path.basename(video_path)}")
        cmd = [
            FFPROBE_PATH,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-skip_frame', 'nokey',
            '-show_entries', 'frame=best_effort_timestamp_time,pkt_pts_time,pts_time',
            '-of', 'json',
            video_path,
        ]
        result = _run_media_command(cmd, timeout=120)
        if result.returncode != 0 or not result.stdout.strip():
            return []

        data = json.loads(result.stdout)
        keyframes = []
        for frame in data.get('frames', []):
            ts = frame.get('best_effort_timestamp_time') or frame.get('pkt_pts_time') or frame.get('pts_time')
            if ts is None:
                continue
            try:
                t = float(ts)
            except (TypeError, ValueError):
                continue
            if t >= 0.0:
                keyframes.append(round(t, 3))

        keyframes = sorted(set(keyframes))
        cleaned = []
        for t in keyframes:
            if not cleaned or t - cleaned[-1] >= min_interval:
                cleaned.append(t)

        print(f"   ✓ Found {len(cleaned)} codec keyframes")
        return cleaned
    except subprocess.TimeoutExpired:
        print("   ⚠️  Warning: Keyframe detection timeout")
        return []
    except Exception as e:
        print(f"   ⚠️  Warning: Could not read keyframes: {e}")
        return []
