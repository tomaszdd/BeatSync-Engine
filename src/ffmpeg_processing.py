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


def create_looping_image_video(image_file: str, output_file: str, duration: float,
                               fps: float, use_nvenc: bool = False,
                               gpu_encoder: str = 'h264_nvenc', lossless: bool = False,
                               target_size: Tuple[int, int] | None = None) -> str:
    """Turn a still image into a silent CFR MP4 source for the render pipeline."""
    duration = max(0.1, float(duration))
    fps = max(1.0, float(fps))
    # Scale to the final output size now (not the native photo resolution) so we don't
    # push multi-megapixel frames through the filter/encoder for the whole song length.
    # Portrait / non-16:9 photos are letterboxed, never stretched.
    scale_filter = (
        build_fit_scale_filter(target_size[0], target_size[1]) if target_size
        else "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"
    )

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
    ~1/3 of the frame, keep a generous floor so it always reads big, and cap it
    so it never grows past the frame width or a third of the height. For a
    multi-line title the longest line drives the width.
    """
    lines = [ln for ln in str(text or '').strip().splitlines() if ln.strip()]
    n = max(1, max((len(ln) for ln in lines), default=len(str(text or '').strip())))
    aim_width = 0.34 * frame_w                      # target: about a third of the width
    by_width = aim_width / (0.5 * n)
    floor = frame_h / 10.0                          # always clearly visible
    ceil_w = (0.95 * frame_w) / (0.5 * n)           # never overflow the frame
    ceil_h = frame_h / 3.0                          # never taller than a third
    size = min(max(by_width, floor), ceil_w, ceil_h)
    return int(max(16, round(size)))


def add_text_overlays_ffmpeg(output_file: str, start_text: str = '',
                              start_position: str = 'bottom_center', start_duration: float = 3.0,
                              end_text: str = '', end_position: str = 'bottom_center',
                              end_duration: float = 3.0, use_nvenc: bool = False,
                              gpu_encoder: str = 'h264_nvenc', fps: float = 30.0,
                              font_file: str | None = None,
                              fade_in: float = 0.0, fade_out: float = 0.0,
                              title_card_enabled: bool = False,
                              title_theme: str | None = None,
                              theme_preset: Optional[Any] = None) -> str:
    """Burn optional start/end titles and/or a black fade in/out into an assembled video.

    If title_card_enabled is True and start_text is non-empty, applies a blur-to-sharp
    title card opening that smoothly resolves into the sharp first clip footage,
    using the chosen visual theme (typography, color grade, and graphic overlay).
    Otherwise, burns standard text overlay(s).
    """
    start_clean = str(start_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    end_clean = str(end_text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    have_text = bool(start_clean or end_clean)
    fade_in = max(0.0, float(fade_in or 0.0))
    fade_out = max(0.0, float(fade_out or 0.0))
    if not have_text and fade_in <= 0.0 and fade_out <= 0.0:
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

        if has_subtitle:
            title_font_size = _title_font_size(title_text, frame_w, frame_h)
            sub_font_size = max(16, int(round(title_font_size * 0.52)))
            gap = max(10, int(round(sub_font_size * 0.55)))
            total_block_h = title_font_size + gap + sub_font_size

            title_y = f"(h-{total_block_h})/2"
            sub_y = f"(h-{total_block_h})/2+{title_font_size}+{gap}"
            title_x = "(w-text_w)/2"
            sub_x = "(w-text_w)/2"

            t_filter = _make_custom_text_filter(title_text, t_font, title_font_size, t_color, title_x, title_y, 0.0, window, alpha_expr=title_alpha)
            s_filter = _make_custom_text_filter(subtitle_text, s_font, sub_font_size, s_color, sub_x, sub_y, 0.0, window, alpha_expr=title_alpha)
            title_text_chain = f"{t_filter},{s_filter}"
        else:
            title_font_size = _title_font_size(start_clean, frame_w, frame_h)
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
            fc_parts.append(f"[v_title]{','.join(post_filters)}[v_out]")
        else:
            fc_parts.append(f"[v_title]null[v_out]")

        filter_complex_str = "; ".join(fc_parts)
        is_complex = True
        desc = "blur-to-sharp title card"
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
                                low_priority: bool = False) -> bool:
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
        
        # Scale to target size, keeping aspect ratio (portrait sources get
        # letter-/pillar-boxed instead of stretched to 16:9).
        if target_size:
            width, height = target_size
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
