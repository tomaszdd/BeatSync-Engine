"""AI mood-matched title typography, graphics treatments, and themed transitions.

Provides curated visual themes (Warm & Sentimental, Joyful & Bright, Upbeat & Energetic)
backed by bundled Google Fonts, procedural graphic treatments, and color grade tints,
driven by explainable mood signature analysis over emotion tags and audio features.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple, Any

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
