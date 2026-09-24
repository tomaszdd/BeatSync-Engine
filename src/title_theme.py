"""AI mood-matched title typography, graphics treatments, and themed transitions.

Provides curated visual themes (Warm & Sentimental, Joyful & Bright, Upbeat & Energetic)
backed by bundled Google Fonts, procedural graphic treatments, and color grade tints,
driven by explainable mood signature analysis over emotion tags and audio features.
"""

from __future__ import annotations

import os
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple, Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Root directory for bundled assets
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(REPO_ROOT, "assets", "fonts")

THEME_WARM_SENTIMENTAL = "Warm & Sentimental"
THEME_JOYFUL_BRIGHT = "Joyful & Bright"
THEME_UPBEAT_ENERGETIC = "Upbeat & Energetic"
THEME_AUTO = "Auto (AI mood match)"

THEME_CHOICES = [
    THEME_AUTO,
    THEME_WARM_SENTIMENTAL,
    THEME_JOYFUL_BRIGHT,
    THEME_UPBEAT_ENERGETIC,
]


@dataclass
class ThemePreset:
    name: str
    id: str
    title_font: str
    subtitle_font: str
    title_color: str
    subtitle_color: str
    # Color grade applied during title card opening footage
    title_color_grade_eq: str
    # Procedural graphic overlay filter
    graphic_overlay_type: str
    # Subtle color-temperature / flash filter applied during crossfades
    transition_tint_eq: str
    # Transition xfade type
    xfade_transition: str
    description: str
    # Decorative graphic motif around title text (e.g. corner brackets, confetti dots, chevrons)
    decorative_motif_type: str = ""


@dataclass
class MoodSignature:
    warmth: float
    energy: float
    dominant_emotion: str
    emotion_counts: Dict[str, int]
    avg_wave: float
    avg_rhythm: float
    avg_impact: float
    section_types: List[str]
    selected_theme: str
    reason: str


def _font_path(filename: str) -> str:
    path = os.path.join(FONTS_DIR, filename)
    if os.path.isfile(path):
        return path
    # Fallback to font path relative to current working directory
    cwd_path = os.path.join(os.getcwd(), "assets", "fonts", filename)
    if os.path.isfile(cwd_path):
        return cwd_path
    return path


THEME_PRESETS: Dict[str, ThemePreset] = {
    THEME_WARM_SENTIMENTAL: ThemePreset(
        name=THEME_WARM_SENTIMENTAL,
        id="warm_sentimental",
        title_font=_font_path("PlayfairDisplay-Bold.ttf"),
        subtitle_font=_font_path("Montserrat-Regular.ttf"),
        title_color="white",
        subtitle_color="0xe8d5b5",  # Warm champagne/gold tint
        title_color_grade_eq="brightness=-0.14:contrast=0.92:gamma_r=1.10:gamma_b=0.90",
        graphic_overlay_type="bokeh_light_leak",
        # Crossfade gets a very subtle warm color-temperature shift during the blend
        transition_tint_eq="gamma_r=1.12:gamma_b=0.88:saturation=1.06",
        xfade_transition="fade",
        description="Warm amber/gold tint, elegant serif title, soft procedural bokeh/light-leak overlay, warm crossfade blend.",
        decorative_motif_type="corner_brackets_leaf",
    ),
    THEME_JOYFUL_BRIGHT: ThemePreset(
        name=THEME_JOYFUL_BRIGHT,
        id="joyful_bright",
        title_font=_font_path("Quicksand-Bold.ttf"),
        subtitle_font=_font_path("Poppins-Regular.ttf"),
        title_color="white",
        subtitle_color="0xffe4d6",  # Soft pastel peach/rose tint
        title_color_grade_eq="brightness=-0.08:contrast=0.95:gamma_r=1.06:gamma_g=1.02:gamma_b=1.04:saturation=1.08",
        graphic_overlay_type="light_particles",
        # Crossfade gets a gentle warm light-leak flash during the blend
        transition_tint_eq="brightness=0.08:gamma_r=1.08:gamma_b=0.96:saturation=1.10",
        xfade_transition="fade",
        description="Pastel pink-gold grade, friendly rounded sans title, soft floating light particles, gentle light-leak transition flash.",
        decorative_motif_type="confetti_dots",
    ),
    THEME_UPBEAT_ENERGETIC: ThemePreset(
        name=THEME_UPBEAT_ENERGETIC,
        id="upbeat_energetic",
        title_font=_font_path("BebasNeue-Regular.ttf"),
        subtitle_font=_font_path("Oswald-Regular.ttf"),
        title_color="white",
        subtitle_color="0xffffff",  # High contrast crisp white
        title_color_grade_eq="brightness=-0.12:contrast=1.06:saturation=1.16",
        graphic_overlay_type="light_streaks",
        # Crossfade gets an energetic punchy streak/flash during the blend
        transition_tint_eq="contrast=1.15:brightness=0.10:saturation=1.20",
        xfade_transition="fade",
        description="Punchy contrasty grade, bold condensed display face, dynamic light streaks, punchy transition streak/flash.",
        decorative_motif_type="angular_chevrons",
    ),
}


def compute_mood_signature(
    clips: Sequence[Dict[str, Any]] | None = None,
    beat_info: Dict[str, Any] | None = None,
) -> MoodSignature:
    """Analyze emotion tags, audio energy, and section mix to form an explainable mood signature.

    2D scoring axes:
    - warmth/sentiment axis (0.0 - 1.0): dominated by 'soft', 'sad', and 'beauty' tags.
    - energy axis (0.0 - 1.0): audio energy wave average, rhythm strength, and impact scores.
    """
    emotion_counts: Dict[str, int] = {}
    clips = clips or []
    
    # Aggregate tags from clips
    for clip in clips:
        tags = clip.get("tags") or []
        for t in tags:
            tag_clean = str(t).lower().strip()
            emotion_counts[tag_clean] = emotion_counts.get(tag_clean, 0) + 1

    # Extract audio energy signals
    av_profile = (beat_info or {}).get("audio_visual_profile") or {}
    energy_profile = (beat_info or {}).get("energy_profile") or {}
    rhythm_data = (beat_info or {}).get("rhythm_data") or {}

    avg_wave = float(av_profile.get("average_wave") or 0.5)
    if "wave" in energy_profile and len(energy_profile["wave"]) > 0:
        try:
            import numpy as np
            avg_wave = float(np.mean(energy_profile["wave"]))
        except Exception:
            pass

    avg_rhythm = float(av_profile.get("average_rhythm") or 0.5)
    avg_impact = float(av_profile.get("average_impact") or 0.5)

    sections = (beat_info or {}).get("sections") or []
    section_types = [str(s.get("type", "verse")) for s in sections]

    # Weighted tag buckets
    warm_count = (
        emotion_counts.get("soft", 0) * 1.2
        + emotion_counts.get("sad", 0) * 1.5
        + emotion_counts.get("beauty", 0) * 0.6
        + emotion_counts.get("flow", 0) * 0.4
    )
    energetic_count = (
        emotion_counts.get("hype", 0) * 1.5
        + emotion_counts.get("tension", 0) * 1.0
        + emotion_counts.get("action", 0) * 0.8
        + emotion_counts.get("drop", 0) * 0.8
    )
    bright_count = (
        emotion_counts.get("neutral", 0) * 1.0
        + emotion_counts.get("clean", 0) * 0.3
        + emotion_counts.get("soft", 0) * 0.5
    )

    total_sentiment_weight = warm_count + energetic_count + bright_count
    if total_sentiment_weight > 0:
        warmth_score = round(min(1.0, max(0.0, warm_count / total_sentiment_weight)), 3)
    else:
        warmth_score = 0.5

    energy_score = round(min(1.0, max(0.0, 0.6 * avg_wave + 0.4 * avg_rhythm)), 3)

    # Determine dominant emotion
    known_emotions = ["soft", "tension", "hype", "sad", "neutral"]
    ranked_emotions = sorted(
        known_emotions,
        key=lambda e: emotion_counts.get(e, 0),
        reverse=True,
    )
    dominant_emotion = ranked_emotions[0] if ranked_emotions else "neutral"

    # Decision logic
    if (energetic_count > warm_count and energy_score >= 0.55) or (energy_score >= 0.70 and emotion_counts.get("hype", 0) > 0):
        selected_theme = THEME_UPBEAT_ENERGETIC
        reason = (
            f"High energy ({energy_score:.2f}) and energetic tags (tension/hype/action={energetic_count:.1f} "
            f"vs warm={warm_count:.1f})."
        )
    elif warm_count > 0 and (warmth_score >= 0.35 or dominant_emotion in ("soft", "sad")):
        selected_theme = THEME_WARM_SENTIMENTAL
        reason = (
            f"Dominant warm/sentimental tags (soft={emotion_counts.get('soft', 0)}, "
            f"beauty={emotion_counts.get('beauty', 0)}, warmth={warmth_score:.2f}) with moderate energy ({energy_score:.2f})."
        )
    elif dominant_emotion == "neutral" or bright_count > 0 or energy_score >= 0.45:
        selected_theme = THEME_JOYFUL_BRIGHT
        reason = (
            f"Bright/balanced profile (bright={bright_count:.1f}, warmth={warmth_score:.2f}) "
            f"with moderate energy ({energy_score:.2f})."
        )
    else:
        selected_theme = THEME_WARM_SENTIMENTAL
        reason = (
            f"Fallback to Warm & Sentimental (warmth={warmth_score:.2f}, energy={energy_score:.2f})."
        )

    return MoodSignature(
        warmth=warmth_score,
        energy=energy_score,
        dominant_emotion=dominant_emotion,
        emotion_counts=emotion_counts,
        avg_wave=round(avg_wave, 3),
        avg_rhythm=round(avg_rhythm, 3),
        avg_impact=round(avg_impact, 3),
        section_types=section_types,
        selected_theme=selected_theme,
        reason=reason,
    )


def resolve_theme(
    theme_choice: str | None,
    clips: Sequence[Dict[str, Any]] | None = None,
    beat_info: Dict[str, Any] | None = None,
) -> Tuple[ThemePreset, MoodSignature]:
    """Resolve theme preset either by auto mood-matching or explicit user selection."""
    mood_sig = compute_mood_signature(clips, beat_info)

    choice = str(theme_choice or THEME_AUTO).strip()
    if choice in THEME_PRESETS:
        preset = THEME_PRESETS[choice]
        mood_sig.reason = f"Manual override: user explicitly selected '{choice}'."
        mood_sig.selected_theme = choice
        return preset, mood_sig

    # Auto mode or unrecognized fallback
    matched_name = mood_sig.selected_theme
    preset = THEME_PRESETS.get(matched_name, THEME_PRESETS[THEME_WARM_SENTIMENTAL])
    return preset, mood_sig


def _hex_to_rgba(c_str: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    """Parse color string (hex 0x..., #..., or name) into RGBA tuple."""
    c_str = str(c_str or "").strip()
    if c_str.startswith("0x") or c_str.startswith("0X"):
        val = int(c_str, 16)
        r = (val >> 16) & 0xFF
        g = (val >> 8) & 0xFF
        b = val & 0xFF
        return (r, g, b, alpha)
    elif c_str.startswith("#"):
        val = int(c_str[1:], 16)
        r = (val >> 16) & 0xFF
        g = (val >> 8) & 0xFF
        b = val & 0xFF
        return (r, g, b, alpha)
    elif c_str.lower() == "white":
        return (255, 255, 255, alpha)
    return (255, 255, 255, alpha)


def _compute_text_layout(
    preset: ThemePreset,
    width: int,
    height: int,
    title_text: str,
    subtitle_text: str = "",
) -> Tuple[Tuple[float, float, float, float], int, int, int, float, float]:
    """Calculate text bounding box and layout positions matching ffmpeg drawtext."""
    title_clean = str(title_text or "").strip()
    sub_clean = str(subtitle_text or "").strip()

    c_count = max(1, len(title_clean))
    title_font_size = int(max(16, round(min(width / (c_count * 0.75 + 4), height * 0.12))))

    if sub_clean:
        sub_font_size = max(16, int(round(title_font_size * 0.52)))
        gap = max(10, int(round(sub_font_size * 0.55)))
        total_block_h = title_font_size + gap + sub_font_size
        title_y = (height - total_block_h) / 2.0
        sub_y = title_y + title_font_size + gap
    else:
        sub_font_size = 0
        gap = 0
        total_block_h = title_font_size
        title_y = (height - total_block_h) / 2.0
        sub_y = title_y

    # Calculate text widths via PIL font measurement
    w_title = float(len(title_clean) * title_font_size * 0.55)
    w_sub = float(len(sub_clean) * sub_font_size * 0.55) if sub_clean else 0.0

    if os.path.isfile(preset.title_font):
        try:
            f_title = ImageFont.truetype(preset.title_font, title_font_size)
            w_title = f_title.getlength(title_clean)
        except Exception:
            pass

    if sub_clean and os.path.isfile(preset.subtitle_font):
        try:
            f_sub = ImageFont.truetype(preset.subtitle_font, sub_font_size)
            w_sub = f_sub.getlength(sub_clean)
        except Exception:
            pass

    max_w = max(w_title, w_sub)
    x0 = (width - max_w) / 2.0
    x1 = (width + max_w) / 2.0
    y0 = title_y
    y1 = y0 + total_block_h

    return (x0, y0, x1, y1), title_font_size, sub_font_size, gap, title_y, sub_y


def _draw_corner_brackets_leaf(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    bbox: Tuple[float, float, float, float],
    accent_hex: str,
    title_y: float,
    sub_y: float,
    has_subtitle: bool,
):
    """Draw delicate double-hairline corner brackets and a minimal botanical leaf flourish."""
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) / 2.0
    scale = height / 1080.0

    c_outer = _hex_to_rgba(accent_hex, 225)
    c_inner = _hex_to_rgba(accent_hex, 165)

    pad_x = max(40, int(50 * scale))
    pad_y = max(24, int(35 * scale))
    bx0 = max(20.0, x0 - pad_x)
    by0 = max(20.0, y0 - pad_y)
    bx1 = min(float(width - 20), x1 + pad_x)
    by1 = min(float(height - 20), y1 + pad_y)

    arm = max(28, int(52 * scale))
    inset = max(5, int(7 * scale))
    arm_inner = max(16, arm - int(12 * scale))
    lw = max(1, int(round(1.8 * scale)))

    # Outer corner brackets
    # Top-Left
    draw.line([(bx0, by0), (bx0 + arm, by0)], fill=c_outer, width=lw)
    draw.line([(bx0, by0), (bx0, by0 + arm)], fill=c_outer, width=lw)
    # Top-Right
    draw.line([(bx1 - arm, by0), (bx1, by0)], fill=c_outer, width=lw)
    draw.line([(bx1, by0), (bx1, by0 + arm)], fill=c_outer, width=lw)
    # Bottom-Left
    draw.line([(bx0, by1), (bx0 + arm, by1)], fill=c_outer, width=lw)
    draw.line([(bx0, by1 - arm), (bx0, by1)], fill=c_outer, width=lw)
    # Bottom-Right
    draw.line([(bx1 - arm, by1), (bx1, by1)], fill=c_outer, width=lw)
    draw.line([(bx1, by1 - arm), (bx1, by1)], fill=c_outer, width=lw)

    # Inner delicate hairlines
    ibx0, iby0, ibx1, iby1 = bx0 + inset, by0 + inset, bx1 - inset, by1 - inset
    draw.line([(ibx0, iby0), (ibx0 + arm_inner, iby0)], fill=c_inner, width=lw)
    draw.line([(ibx0, iby0), (ibx0, iby0 + arm_inner)], fill=c_inner, width=lw)
    draw.line([(ibx1 - arm_inner, iby0), (ibx1, iby0)], fill=c_inner, width=lw)
    draw.line([(ibx1, iby0), (ibx1, iby0 + arm_inner)], fill=c_inner, width=lw)
    draw.line([(ibx0, iby1), (ibx0 + arm_inner, iby1)], fill=c_inner, width=lw)
    draw.line([(ibx0, iby1 - arm_inner), (ibx0, iby1)], fill=c_inner, width=lw)
    draw.line([(ibx1 - arm_inner, iby1), (ibx1, iby1)], fill=c_inner, width=lw)
    draw.line([(ibx1, iby1 - arm_inner), (ibx1, iby1)], fill=c_inner, width=lw)

    # Minimal motif placed near the subtitle line:
    # A delicate botanical laurel sprig with central diamond flourish centered below text
    my = y1 + max(18.0, 24.0 * scale)
    sprig_w = int(55 * scale)
    # Central stem hairline
    draw.line([(cx - sprig_w, my), (cx + sprig_w, my)], fill=c_outer, width=lw)
    # Center diamond dot
    dia_r = max(2, int(3 * scale))
    draw.polygon(
        [(cx, my - dia_r), (cx + dia_r, my), (cx, my + dia_r), (cx - dia_r, my)],
        fill=c_outer,
    )

    # Symmetrical leaf pairs branching from stem
    for side in (-1, 1):
        # Outer leaf
        lx1 = cx + side * int(32 * scale)
        lx_tip = cx + side * int(44 * scale)
        ly_tip = my - int(9 * scale)
        draw.polygon(
            [
                (lx1, my),
                (cx + side * int(36 * scale), my - int(7 * scale)),
                (lx_tip, ly_tip),
                (cx + side * int(40 * scale), my - int(3 * scale)),
            ],
            fill=c_outer,
        )
        # Inner leaf
        lx2 = cx + side * int(14 * scale)
        lx2_tip = cx + side * int(22 * scale)
        ly2_tip = my - int(8 * scale)
        draw.polygon(
            [
                (lx2, my),
                (cx + side * int(16 * scale), my - int(6 * scale)),
                (lx2_tip, ly2_tip),
                (cx + side * int(19 * scale), my - int(3 * scale)),
            ],
            fill=c_outer,
        )


def _draw_confetti_dots(
    img: Image.Image,
    width: int,
    height: int,
    bbox: Tuple[float, float, float, float],
    accent_hex: str,
):
    """Draw a scatter of gentle soft-edged confetti circles around the text block."""
    x0, y0, x1, y1 = bbox
    scale = height / 1080.0

    colors = [
        _hex_to_rgba(accent_hex, 195),           # Theme pastel peach
        (255, 209, 193, 180),                    # Warm pastel rose
        (255, 242, 222, 190),                    # Golden cream
        (250, 215, 220, 175),                    # Soft blush
        (255, 235, 205, 165),                    # Pale apricot
    ]

    dot_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dot_draw = ImageDraw.Draw(dot_layer)

    rng = random.Random(42)
    pad_x = max(35.0, 50.0 * scale)
    pad_y = max(25.0, 35.0 * scale)
    bx0, by0, bx1, by1 = x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y

    dots = []
    # Left zone flanking margin
    for _ in range(12):
        dx = rng.uniform(max(15.0, bx0 - 140.0 * scale), bx0)
        dy = rng.uniform(by0 - 30.0 * scale, by1 + 30.0 * scale)
        r = rng.uniform(3.0 * scale, 10.0 * scale)
        c = rng.choice(colors)
        dots.append((dx, dy, r, c))

    # Right zone flanking margin
    for _ in range(12):
        dx = rng.uniform(bx1, min(float(width - 15), bx1 + 140.0 * scale))
        dy = rng.uniform(by0 - 30.0 * scale, by1 + 30.0 * scale)
        r = rng.uniform(3.0 * scale, 10.0 * scale)
        c = rng.choice(colors)
        dots.append((dx, dy, r, c))

    # Top zone above title
    for _ in range(7):
        dx = rng.uniform(bx0 + 20.0 * scale, bx1 - 20.0 * scale)
        dy = rng.uniform(max(15.0, by0 - 55.0 * scale), by0)
        r = rng.uniform(2.5 * scale, 8.0 * scale)
        c = rng.choice(colors)
        dots.append((dx, dy, r, c))

    # Bottom zone below subtitle
    for _ in range(7):
        dx = rng.uniform(bx0 + 20.0 * scale, bx1 - 20.0 * scale)
        dy = rng.uniform(by1, min(float(height - 15), by1 + 55.0 * scale))
        r = rng.uniform(2.5 * scale, 8.0 * scale)
        c = rng.choice(colors)
        dots.append((dx, dy, r, c))

    for dx, dy, r, c in dots:
        dot_draw.ellipse([(dx - r, dy - r), (dx + r, dy + r)], fill=c)

    # Soften edges slightly for gentle floating confetti
    dot_layer = dot_layer.filter(ImageFilter.GaussianBlur(radius=max(0.6, 0.8 * scale)))
    img.alpha_composite(dot_layer)


def _draw_angular_chevrons(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    bbox: Tuple[float, float, float, float],
    accent_hex: str,
    title_y: float,
    title_font_size: int,
    sub_y: float,
    has_subtitle: bool,
):
    """Draw bold dynamic angular chevrons flanking the title and sleek divider."""
    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) / 2.0
    scale = height / 1080.0

    c_white = _hex_to_rgba(accent_hex, 240)
    c_white_soft = _hex_to_rgba(accent_hex, 165)

    cy_title = title_y + title_font_size / 2.0
    chev_h = int(38 * scale)
    chev_w = int(20 * scale)
    lw = max(3, int(5 * scale))

    x_left = x0 - max(40.0, 60.0 * scale)
    x_right = x1 + max(40.0, 60.0 * scale)

    # Left chevrons: <<
    p1 = (x_left, cy_title - chev_h)
    p2 = (x_left - chev_w, cy_title)
    p3 = (x_left, cy_title + chev_h)
    draw.line([p1, p2, p3], fill=c_white, width=lw, joint="miter")

    off = int(24 * scale)
    p1o = (x_left - off, cy_title - chev_h * 0.8)
    p2o = (x_left - off - chev_w * 0.8, cy_title)
    p3o = (x_left - off, cy_title + chev_h * 0.8)
    draw.line([p1o, p2o, p3o], fill=c_white_soft, width=max(2, lw - 1), joint="miter")

    # Right chevrons: >>
    rp1 = (x_right, cy_title - chev_h)
    rp2 = (x_right + chev_w, cy_title)
    rp3 = (x_right, cy_title + chev_h)
    draw.line([rp1, rp2, rp3], fill=c_white, width=lw, joint="miter")

    rp1o = (x_right + off, cy_title - chev_h * 0.8)
    rp2o = (x_right + off + chev_w * 0.8, cy_title)
    rp3o = (x_right + off, cy_title + chev_h * 0.8)
    draw.line([rp1o, rp2o, rp3o], fill=c_white_soft, width=max(2, lw - 1), joint="miter")

    # Sleek horizontal divider line between title and subtitle if subtitle is present
    if has_subtitle:
        div_y = (title_y + title_font_size + sub_y) / 2.0
        div_w = int(60 * scale)
        draw.line(
            [(cx - div_w, div_y), (cx + div_w, div_y)],
            fill=_hex_to_rgba(accent_hex, 180),
            width=max(2, int(2.5 * scale)),
        )


def render_decorative_motif(
    preset: ThemePreset,
    width: int,
    height: int,
    title_text: str = "",
    subtitle_text: str = "",
    output_path: str | None = None,
) -> Image.Image | str:
    """Render designed decorative motif (border brackets, confetti, or chevrons) as RGBA PNG."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox, t_size, s_size, gap, t_y, s_y = _compute_text_layout(
        preset, width, height, title_text, subtitle_text
    )
    has_sub = bool(str(subtitle_text or "").strip())
    motif_type = getattr(preset, "decorative_motif_type", "") or ""

    if motif_type == "corner_brackets_leaf" or preset.id == "warm_sentimental":
        _draw_corner_brackets_leaf(
            draw, width, height, bbox, preset.subtitle_color, t_y, s_y, has_sub
        )
    elif motif_type == "confetti_dots" or preset.id == "joyful_bright":
        _draw_confetti_dots(
            img, width, height, bbox, preset.subtitle_color
        )
    elif motif_type == "angular_chevrons" or preset.id == "upbeat_energetic":
        _draw_angular_chevrons(
            draw, width, height, bbox, preset.subtitle_color, t_y, t_size, s_y, has_sub
        )

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path, "PNG")
        return output_path

    return img
