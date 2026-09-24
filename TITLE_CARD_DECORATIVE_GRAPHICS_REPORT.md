# Designed Decorative Graphics for Title Cards — Verification & Implementation Report

## Executive Summary

This report documents the design, implementation, unit testing, and real-hardware verification of designed decorative graphic elements for the title card system, as specified in `TITLE_CARD_DECORATIVE_GRAPHICS_TASK_SPEC.md`.

Previously, the title card system featured procedural background textures (`bokeh_light_leak`, `light_particles`, `light_streaks` generated via `noise` + `gblur` + `eq`). While atmospheric, they lacked designed graphic identity. To elevate the visual presentation without introducing heavy machine learning or external API dependencies, pure Python/Pillow vector-drawn decorative motifs were designed and implemented for each of the three title themes, matching their established typography and accent colors.

### Key Deliverables
1. **Designed Motifs per Theme** (`src/title_theme.py`):
   - **Warm & Sentimental**: Champagne-gold (`#e8d5b5`) double-hairline corner brackets framing the text block, paired with a delicate botanical laurel leaf sprig and central diamond flourish centered below the subtitle line. Matches Playfair Display's formal elegance.
   - **Joyful & Bright**: A floating scatter of soft-edged pastel confetti circles/dots flanking and framing the text block in pastel peach (`#ffe4d6`), warm rose, golden cream, soft blush, and pale apricot. Matches Quicksand's rounded friendliness.
   - **Upbeat & Energetic**: Bold dynamic angular chevrons (`<<` and `>>`) flanking the title line in bright white (`#ffffff`) with secondary ghost chevrons, plus a sleek horizontal divider line between title and subtitle. Matches Bebas Neue's bold condensed character.
2. **Filtergraph Integration & Critical Leak Prevention** (`src/ffmpeg_processing.py`):
   - Motifs are rendered to transparent RGBA PNGs scaled dynamically to the target render resolution (1080p / 4K).
   - In FFmpeg, the motif PNG is loaded as a looping input (`-loop 1 -t {window} -i {motif_png}`) and faded synchronously with the title window (`fade=t=out:st={t_hold}:d={t_fade}:alpha=1`).
   - **Critical bug prevention**: Guarding against the filter bypass leak documented in `URGENT_BLUR_LEAK_REPORT.md`, the `overlay` filter strictly assigns the video/title text composite stream `[v_text]` as **Input 0** and the motif stream `[motif_fade]` as **Input 1**:
     ```
     [v_text][motif_fade]overlay=0:0:enable='lte(t,{window:.3f})'[v_title]
     ```
     When $t > \text{window}$, FFmpeg's bypass passes Input 0 (`[v_text]`) through untouched, guaranteeing zero trace of graphics, text, or blur leak across the remainder of the timeline.
3. **Verification on UM890 Real Hardware**:
   - **Run A (Full 60s, Auto / Warm & Sentimental)**: Exactly 1800 frames @ 30.0 fps (60.000000s duration), genuine AMD AMF hardware encoding (`Lavc63.1.102 h264_amf`). Corner brackets and laurel leaf motif clearly visible during title window ($t=0.5\text{s}, 1.5\text{s}, 2.5\text{s}$).
   - **Mid-Timeline Zero-Leak Proof**: Thumbnails extracted at $t = 10.0\text{s}, 30.0\text{s}, 50.0\text{s}$ confirm 100% sharp, untouched 4K footage with zero trace of decorative graphics or blur.
   - **Runs B & C (Spot-Checks)**: Confetti dots (Joyful & Bright) and dynamic chevrons (Upbeat & Energetic) verified with clean post-title sharp video.
   - **Unit Tests**: 12/12 title theme tests and 37/37 repo-wide test suite passing on UM890.

---

## Architectural Design & Implementation

### 1. Vector Motif Generation (`src/title_theme.py`)

Each motif is rendered dynamically in pure Python via `PIL.ImageDraw` on a transparent RGBA canvas matching the output render dimensions (`width` $\times$ `height`).

#### Dynamic Typography-Aware Bounding Box
To ensure decorative graphics frame the text perfectly regardless of screen resolution (1080p, 4K, vertical) and text length, `_compute_text_layout()` dynamically calculates the bounding box of the title and subtitle using Pillow's `font.getlength()` and `font.getbbox()`:

```python
def _compute_text_layout(
    preset: ThemePreset,
    width: int,
    height: int,
    title_text: str,
    subtitle_text: str,
) -> Tuple[Tuple[float, float, float, float], int, int, int, float, float]:
    ...
    # Calculates exact (x0, y0, x1, y1) bounding box centered on screen
    # Scales font sizes and padding proportionally to render height
```

#### Theme Motifs

| Theme | Aesthetic Intent | Visual Elements | Palette & Styling |
| :--- | :--- | :--- | :--- |
| **Warm & Sentimental** | Elegant, formal, timeless | • Double-hairline corner brackets around text block<br>• Delicate botanical laurel leaf sprig with central diamond flourish below subtitle | • Champagne Gold (`#e8d5b5`)<br>• Outer brackets: 220 alpha<br>• Inner brackets: 150 alpha<br>• Laurel leaves: solid polygon fill |
| **Joyful & Bright** | Playful, light, celebratory | • Gentle floating confetti scatter surrounding text block<br>• Circular dots of varying radii ($2.5 - 10\text{px}$ scaled)<br>• Subtle Gaussian blur ($0.8\text{px}$) for soft edges | • Preset Peach (`#ffe4d6`, 195 alpha)<br>• Pastel Rose (`#ffd1c1`, 180 alpha)<br>• Golden Cream (`#fff2de`, 190 alpha)<br>• Soft Blush (`#fad7dc`, 175 alpha)<br>• Pale Apricot (`#ffebcd`, 165 alpha) |
| **Upbeat & Energetic** | Bold, athletic, dynamic | • High-contrast double angular chevrons (`<<` and `>>`) flanking title line<br>• Sleek horizontal divider line between title and subtitle | • Pure White (`#ffffff`, 240 alpha)<br>• Ghost chevron (`#ffffff`, 165 alpha)<br>• Accent divider (`#ffffff`, 180 alpha) |

### 2. FFmpeg Filtergraph Integration (`src/ffmpeg_processing.py`)

The decorative motif PNG is created in a temporary file and passed into the FFmpeg command line:
```python
if motif_png_path and os.path.isfile(motif_png_path):
    motif_input_idx = len(ffmpeg_cmd) // 2  # secondary input
    ffmpeg_cmd.extend(["-loop", "1", "-t", f"{window:.3f}", "-i", motif_png_path])
```

#### Filtergraph Layout & Timeline Synchronization
```
[1:v]format=rgba,fade=t=out:st={t_hold:.3f}:d={t_fade:.3f}:alpha=1[motif_fade];
[v_text][motif_fade]overlay=0:0:enable='lte(t,{window:.3f})'[v_title]
```
1. **Looping Input**: `-loop 1 -t {window}` bounds the input reading to the title window.
2. **Synchronous Dissolve**: `fade=t=out:st=t_hold:d=t_fade:alpha=1` transitions the alpha channel to 0 during the fade window, synchronously fading out with the text and background resolve.
3. **Overlay Recombine**: Places the transparent motif over the text composite.

---

## Critical Bug Prevention: Overlay Timeline Bypass

### Background: The Blend Input-Order Bug (`URGENT_BLUR_LEAK_REPORT.md`)
In the previous session, a severe bug was diagnosed where declaring `[themed_bg][orig]blend=...:enable='lte(t,window)'` caused the entire 60s video to be permanently blurred and color-graded. This occurred because FFmpeg multi-input filters with `enable='...'` bypass directly to **Input 0** when the enable condition becomes false.

### Application to `overlay`
The `overlay` filter follows the exact same semantics:
> **FFmpeg Multi-Input Bypass Rule**:
> When a filter is disabled by `enable='...'`, it passes through its **main input (Input 0)** unaltered, while ignoring Input 1.

If the filter had been written as:
```
# BUGGY (DO NOT USE):
[motif_fade][v_text]overlay=0:0:enable='lte(t,window)'[v_title]
```
Then for $t > \text{window}$, FFmpeg would bypass to Input 0 (`[motif_fade]`), resulting in a static frozen frame of the motif PNG playing across the entire video!

### The Correct Implementation
```python
# CORRECT & VERIFIED:
# Input 0: [v_text] (video stream with resolved background & faded text)
# Input 1: [motif_fade] (motif PNG stream)
f"[{curr_v}][motif_fade]overlay=0:0:enable='lte(t,{window:.3f})'[v_title]"
```
- During $t \le \text{window}$: The motif is composited over the video.
- For $t > \text{window}$: `enable` evaluates to false; FFmpeg bypasses directly to Input 0 (`[v_text]`). Since `[v_text]` has already resolved to the sharp original video stream (`orig`) with text alpha at 0, 100% untouched video passes through.

---

## Unit Test Verification

A dedicated suite of unit tests was added to `tests/test_title_theme.py`:
1. `test_render_decorative_motifs_all_themes`:
   - Validates motif rendering for all 3 presets.
   - Asserts correct canvas dimensions (`1920x1080`), RGBA mode, and verifies non-zero alpha pixels exist (ensuring drawings are not blank).
   - Validates file persistence to disk.
2. `test_render_decorative_motif_single_line`:
   - Validates graceful handling when only a title is present with no subtitle.
3. `test_title_card_motif_overlay_input_order_prevents_leak`:
   - Inspects the generated FFmpeg `-filter_complex` command.
   - Asserts `-loop 1 -t` input arguments are present.
   - Asserts `[v_text][motif_fade]overlay=0:0:enable=` ordering is strictly preserved.
   - Asserts `[motif_fade][v_text]overlay=` is NOT present.

### Execution Results on UM890
```
> & 'C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe' -m unittest discover -s C:\BeatSyncTest\app\BeatSync-Engine-main\tests -p test_title_theme.py
...........   📝 Adding blur-to-sharp title card...
   📝 Adding blur-to-sharp title card...
   📝 Adding blur-to-sharp title card...
   📝 Adding blur-to-sharp title card...
.
----------------------------------------------------------------------
Ran 12 tests in 0.284s

OK

> & 'C:\BeatSyncTest\app\BeatSync-Engine-main\venv\Scripts\python.exe' -m unittest discover -s C:\BeatSyncTest\app\BeatSync-Engine-main\tests
.....................................
----------------------------------------------------------------------
Ran 37 tests in 0.479s

OK
```
**Result**: 37/37 tests pass with 100% success rate.

---

## Real Hardware Verification on UM890

Hardware verification was performed directly on the target host `um890` using the production GoPro dataset:
- **Host**: Minisforum UM890 Pro (AMD Ryzen 9 8945HS with Radeon 780M Graphics)
- **Dataset**: `D:\Photos\GoPro\2025-10-01 Tereska Birth\` (15 4K60 HEVC video files)
- **Audio**: `C:\BeatSyncTest\audio_60s.mp3` (60.03s duration)
- **Settings**: Journey mode, quality filter, `min_subject_confidence=0.3`, transitions enabled, title card enabled (`start_text="Teresa S. Dunn\n1st October 2025"`).

### Run Summary

| Run | Preset / Theme | Mode | Render Time | Duration | Packets / FPS | Hardware Encoder | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Run A** | Warm & Sentimental | Full 60s Render (`Auto`) | 106.69s | 60.000000s | 1800 packets (30.0 fps) | `Lavc63.1.102 h264_amf` | **PASS** |
| **Run B** | Joyful & Bright | Spot-Check (10s) | 33.72s | 10.000000s | 300 packets (30.0 fps) | `Lavc63.1.102 h264_amf` | **PASS** |
| **Run C** | Upbeat & Energetic | Spot-Check (10s) | 28.75s | 10.000000s | 300 packets (30.0 fps) | `Lavc63.1.102 h264_amf` | **PASS** |

### Run A Detailed Telemetry (Warm & Sentimental — Full 60s)
```json
{
  "output": "C:\\BeatSyncTest\\app\\BeatSync-Engine-main\\output\\verify_decorative_run_a_auto.mp4",
  "render_time_s": 106.69,
  "frame_count": 1800,
  "duration": 60.0,
  "encoder": "Lavc63.1.102 h264_amf",
  "theme_name": "Warm & Sentimental",
  "decorative_motif": "corner_brackets_leaf"
}
```

### Visual & Frame Analysis

All thumbnails were fetched and verified from `docs/thumbnails/decorative_graphics/`:

| Timestamp | Phase / Content | File Size | Motif / Visual Analysis | Zero-Leak Verification |
| :--- | :--- | :--- | :--- | :--- |
| **$t = 0.5\text{s}$** | Title Card Hold | 227,463 B | Corner brackets + botanical laurel leaf sprig sharp and visible alongside Playfair Display Bold typography. | N/A (Title window active) |
| **$t = 1.5\text{s}$** | Title Card Hold | 244,417 B | Peak visibility; champagne gold hairlines frame the title text with warm amber background grade and bokeh. | N/A (Title window active) |
| **$t = 2.5\text{s}$** | Title Card Fade | 272,129 B | Smooth alpha dissolve in progress; brackets and sprig fading synchronously with text and background unblur. | N/A (Title window active) |
| **$t = 10.0\text{s}$** | Mid-Timeline Video | 382,674 B | Mother and newborn baby in hospital bed; crisp 4K spatial detail, natural colors. | **CONFIRMED**: Zero trace of brackets, leaf, text, or blur leak. |
| **$t = 30.0\text{s}$** | Mid-Timeline Video | 397,751 B | Hallway walking shot; sharp doorway edges, floor tiles, and backpack straps. | **CONFIRMED**: Zero trace of brackets, leaf, text, or blur leak. |
| **$t = 50.0\text{s}$** | Mid-Timeline Video | 419,008 B | Underground car park; sharp brick textures and license plate. | **CONFIRMED**: Zero trace of brackets, leaf, text, or blur leak. |

### Runs B & C Spot-Checks

| Run | Motif Name | Title Window Thumbnail ($t = 1.0\text{s}$) | Post-Title Thumbnail ($t = 6.0\text{s}$) | Visual Confirmation |
| :--- | :--- | :--- | :--- | :--- |
| **Run B (Joyful)** | `confetti_dots` | `run_b_joyful_1.0s.jpg` (229,504 B) | `run_b_joyful_6.0s.jpg` (1,054,589 B) | Soft pastel confetti circles frame Quicksand text block; $t=6.0\text{s}$ is 100% sharp with zero confetti dots. |
| **Run C (Upbeat)** | `angular_chevrons` | `run_c_upbeat_1.0s.jpg` (240,723 B) | `run_c_upbeat_6.0s.jpg` (1,040,677 B) | Bold white chevrons (`<<` and `>>`) flank Bebas Neue title with divider line; $t=6.0\text{s}$ is 100% sharp with zero chevrons. |

---

## Git Verification & Push

Below is the verification showing the commit history, pushed state, and clean working tree.

### `git status` (Executed after push)
```
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

### `git log origin/main..HEAD` (Executed after push)
```
(empty - 0 unpushed commits; local HEAD matches origin/main)
```

### `git log -1`
```
commit fc277b292350a4b2f8295b792971c32b0c248ba9 (HEAD -> main, origin/main, origin/HEAD)
Author: pi <pi@scratch>
Date:   Thu Sep 24 13:34:05 2026 +0100

    feat(title-theme): add designed decorative graphics motifs to title card
```
