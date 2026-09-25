#!/usr/bin/env python3
"""Shared project paths and directory helpers."""

import os

from logger import ROOT_DIR


INPUT_DIR = os.path.join(ROOT_DIR, 'input')
AUDIO_INPUT_DIR = os.path.join(INPUT_DIR, 'audio')
VIDEO_INPUT_DIR = os.path.join(INPUT_DIR, 'video')
PROCESSING_DIR = os.path.join(INPUT_DIR, 'processing')
GRADIO_TEMP_DIR = os.path.join(INPUT_DIR, 'gradio_uploads')
IMAGE_LOOP_CACHE_DIR = os.path.join(INPUT_DIR, 'image_loop_cache')

# Persistent, user-configurable render output location (survives scratch-env rebuilds,
# same pattern as D:\BeatSync\Models\ and D:\BeatSync\Assets\). GUI-settable at runtime
# via set_output_dir(); falls back to this default when unset/blank.
DEFAULT_OUTPUT_DIR = r'D:\BeatSync\Output'
_current_output_dir = DEFAULT_OUTPUT_DIR


def ensure_project_dirs() -> None:
    """Create the standard project directories if they are missing."""
    for directory in [
        INPUT_DIR,
        AUDIO_INPUT_DIR,
        VIDEO_INPUT_DIR,
        PROCESSING_DIR,
        GRADIO_TEMP_DIR,
        IMAGE_LOOP_CACHE_DIR,
        _current_output_dir,
    ]:
        os.makedirs(directory, exist_ok=True)


def get_input_dir() -> str:
    """Get the local input directory path."""
    return INPUT_DIR


def get_audio_input_dir() -> str:
    """Get the audio input directory path."""
    return AUDIO_INPUT_DIR


def get_video_input_dir() -> str:
    """Get the video input directory path."""
    return VIDEO_INPUT_DIR


def get_processing_dir() -> str:
    """Get the processing directory path."""
    return PROCESSING_DIR


def get_gradio_temp_dir() -> str:
    """Get the Gradio upload/temp directory path."""
    return GRADIO_TEMP_DIR


def get_image_loop_cache_dir() -> str:
    """Get the persistent cache directory for generated per-image loop videos."""
    return IMAGE_LOOP_CACHE_DIR


def get_output_dir() -> str:
    """Get the current render output directory (user-configurable via the GUI)."""
    return _current_output_dir


def set_output_dir(path: str | None) -> str:
    """Set the render output directory at runtime, creating it if needed.

    Falls back to DEFAULT_OUTPUT_DIR when path is blank. Returns the directory
    actually applied, so callers can normalize a GUI field to the real value.
    """
    global _current_output_dir
    _current_output_dir = (path or '').strip() or DEFAULT_OUTPUT_DIR
    os.makedirs(_current_output_dir, exist_ok=True)
    return _current_output_dir


ASSETS_DIR = os.path.join(ROOT_DIR, 'assets')
DEFAULT_IDENT_ASSET_PATH = os.environ.get(
    'BEATSYNC_IDENT_ASSET_PATH',
    r'D:\BeatSync\Assets\TDD_Intro_3D_1.mov'
)
DEFAULT_WATERMARK_ASSET_PATH = os.path.join(ASSETS_DIR, 'tdd_watermark.png')


def get_ident_asset_path() -> str:
    """Get the path to the 3D branding ident clip."""
    return DEFAULT_IDENT_ASSET_PATH


def get_watermark_asset_path() -> str:
    """Get the path to the static watermark logo PNG."""
    return DEFAULT_WATERMARK_ASSET_PATH


ensure_project_dirs()

