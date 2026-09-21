# Task: Add AMD AMF hardware-encode support alongside existing NVENC

## Context
This repo (`tomaszdd/BeatSync-Engine`) is a fork of `xpix/BeatSync-Engine`, which is
itself a fork of `Merserk/BeatSync-Engine`. It currently only supports NVIDIA hardware
encoding (`h264_nvenc`/`hevc_nvenc`) and CuPy/CUDA-accelerated audio-visual analysis.
Tomasz's target machine (a mini PC on his network) has an **AMD Radeon 780M iGPU**
(RDNA3), which has no CUDA and cannot use CuPy — but it DOES support FFmpeg's AMF
hardware encoder (`h264_amf`/`hevc_amf`), which most modern FFmpeg Windows builds
(including gyan.dev/BtbN builds) ship with when built against AMD's AMF SDK.

**Scope is encoder-only.** Do NOT touch the CuPy/analysis GPU path (`gpu_cpu_utils.py`'s
`get_array_module`/`to_gpu`/`to_cpu`, or `logger.py`'s `get_gpu_info`) — that stays
CUDA-only by design and already gracefully falls back to NumPy/CPU when no CUDA GPU is
present. This task adds a *second, independent* hardware-encode path for the render
stage only, parallel to the existing NVENC one — it must not touch or weaken NVENC
behavior when an NVIDIA GPU is present.

## Files you'll touch
- `src/logger.py`
- `src/gpu_cpu_utils.py`
- `src/ffmpeg_processing.py`
- `src/gui.py`
- `README.md` (append a short section documenting the new option)

## 1. `src/logger.py`
Add a new function near `check_nvenc()` (around line 134):

```python
def check_amf() -> bool:
    """Check if FFmpeg supports AMD hardware encoding (AMF)."""
    try:
        cmd = [FFMPEG_EXE if FFMPEG_FOUND else 'ffmpeg', '-encoders']
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return 'h264_amf' in result.stdout
    except Exception:
        return False
```

Update `print_startup_banner()` to also detect and print AMF availability (mirror
however it currently reports `nvenc`), so the console banner tells the user which
hardware encoder(s), if any, are usable.

## 2. `src/gpu_cpu_utils.py`
Import `check_amf` alongside the existing `check_nvenc` import, and add:

```python
AMF_AVAILABLE = check_amf()
```

right next to the existing `NVENC_AVAILABLE = check_nvenc()` line. Do not change
`GPU_AVAILABLE`/`USE_GPU`/anything CuPy-related — those must stay CUDA-only.

## 3. `src/ffmpeg_processing.py`
There's currently one function, `get_nvenc_quality_args(gpu_encoder, include_pix_fmt)`
(around line 115), used at 4 call sites (search `get_nvenc_quality_args(gpu_encoder`)
gated behind `if use_nvenc:` / `elif use_nvenc:` blocks.

Add a sibling function for AMF, since AMF's ffmpeg flags are different from NVENC's
(no `-cq`/`-multipass`/`-spatial_aq`/`-temporal_aq`/`-rc-lookahead`/`-b_ref_mode` —
those are NVENC-specific and AMF will error or ignore them):

```python
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
```

Then, at every one of the 4 call sites currently doing:
```python
elif use_nvenc:
    cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
```
change the dispatch to pick the right builder based on the encoder family, e.g.:
```python
elif use_hwenc:
    if gpu_encoder in ('h264_nvenc', 'hevc_nvenc'):
        cmd.extend(get_nvenc_quality_args(gpu_encoder, include_pix_fmt=True))
    elif gpu_encoder in ('h264_amf', 'hevc_amf'):
        cmd.extend(get_amf_quality_args(gpu_encoder, include_pix_fmt=True))
```

You have two reasonable options for the boolean flag naming — **pick whichever keeps
the diff smaller and consistent**, and apply it uniformly across all 4 functions
(`create_looping_image_video`, and the other 3 that take `use_nvenc`/`gpu_encoder`
params — search for `use_nvenc: bool` in this file to find all signatures):
- (a) Keep the parameter named `use_nvenc` everywhere but broaden its *meaning* to
  "use hardware encoder" (simplest diff, slightly misleading name), or
- (b) Rename `use_nvenc` → `use_hwenc` throughout this file and its call sites in
  `gui.py`/`video_processor.py` (cleaner, bigger diff).
Prefer (b) if it's a mechanical rename with no behavior risk; fall back to (a) if
renaming touches too many unrelated call sites and risks breaking something.

The preview command around line 662-663 (`preview_cmd.extend(['-hwaccel', 'cuda', ...`)
is NVIDIA-specific decode acceleration for a live preview — leave that one NVENC-only,
it's out of scope (decode-side, not the export encode path this task covers).

## 4. `src/gui.py`
Around line 1444-1445, there's a conditional radio group:
```python
if NVENC_AVAILABLE:
    processing_mode = gr.Radio(choices=[('NVIDIA NVENC H.264', 'h264_nvenc'), ('NVIDIA NVENC HEVC (H.265)', 'hevc_nvenc'), ('CPU (H.264)', 'cpu'), ('ProRes 422 Proxy (Precise Mode)', 'prores_proxy')], value='h264_nvenc', label=LABEL_PROCESSING_MODE, info=get_processing_mode_info_nvenc())
```
Add a parallel `elif AMF_AVAILABLE:` branch offering `('AMD AMF H.264', 'h264_amf')`
and `('AMD AMF HEVC (H.265)', 'hevc_amf')` alongside the existing CPU/ProRes choices
(reuse or write a small `get_processing_mode_info_amf()` analogous to the NVENC one —
check `ui_content.py` for where `get_processing_mode_info_nvenc()` is defined and mirror
its style). Keep the existing plain-CPU `else:` branch (no NVENC, no AMF) unchanged.

Import `AMF_AVAILABLE` alongside the existing `NVENC_AVAILABLE` import (line ~102).

Around line 530-531, generalize:
```python
use_nvenc = (processing_mode in ['h264_nvenc', 'hevc_nvenc']) and NVENC_AVAILABLE
gpu_encoder = processing_mode if use_nvenc else 'none'
```
to also recognize AMF modes, e.g.:
```python
use_hwenc = (
    (processing_mode in ['h264_nvenc', 'hevc_nvenc'] and NVENC_AVAILABLE) or
    (processing_mode in ['h264_amf', 'hevc_amf'] and AMF_AVAILABLE)
)
gpu_encoder = processing_mode if use_hwenc else 'none'
```
and update every downstream use of `use_nvenc` in this file (status messages around
line 678-688, `processing_label`, and the two `plan.get('gpu_encoder', 'none')` call
sites around lines 996/1040 if they reference `use_nvenc`) to the new flag/name
consistently with whatever choice you made in step 3.

Around line 1193, the default mode picker:
```python
'processing_mode': 'h264_nvenc' if NVENC_AVAILABLE else 'cpu',
```
becomes:
```python
'processing_mode': 'h264_nvenc' if NVENC_AVAILABLE else ('h264_amf' if AMF_AVAILABLE else 'cpu'),
```

Status/label text (lines ~678-688) that currently prints things like
`f"{gpu_encoder.upper()} (.mp4)"` and `f"⚡ {gpu_encoder.upper()}"` already works
generically since `gpu_encoder` will just be `'h264_amf'`/`'hevc_amf'` — no per-vendor
string needed there, just make sure the surrounding `if`/`elif` checks the new flag
name instead of the old `use_nvenc`.

## 5. README.md
Add a short subsection (matching the existing "🔧 Fork Changes" style/tone already in
this README) documenting: AMD AMF hardware encode option now available when FFmpeg
reports `h264_amf`/`hevc_amf` support; explicitly note that CuPy-based analysis
acceleration remains NVIDIA/CUDA-only (AMD GPUs get CPU-only analysis, GPU-accelerated
*encoding* only) so nobody expects full parity with an NVIDIA setup.

## Hard constraints
- Do not modify anything under `_to_delete/` (leave it as-is, out of scope).
- Do not touch the CuPy/analysis GPU path — see "Scope" above.
- Do not weaken or change NVENC behavior on a system that has an NVIDIA GPU — this is
  purely additive.
- No deletions of existing files or functions.
- Commit with a clear message (e.g. `feat: add AMD AMF hardware-encode support
  alongside NVENC`), and push to `origin main` on this fork
  (`tomaszdd/BeatSync-Engine`, you have push access via the repo's own git remote).
- When done, write a short report to `/home/pi/projects/BeatSync-Engine/AMD_AMF_REPORT.md`
  summarizing: what changed (file list), the naming choice you made in step 3
  (option a or b and why), whether it builds/imports cleanly (run
  `python -c "import ast; [ast.parse(open(f).read()) for f in ['src/logger.py','src/gpu_cpu_utils.py','src/ffmpeg_processing.py','src/gui.py']]"`
  from the repo root as a basic syntax sanity check since there's no Windows/ffmpeg
  environment here to actually run it), and any open questions/risks for Tomasz to
  check when he actually runs this on the AMD box (there is no way to test AMF
  encoding from this Linux dev environment — flag that clearly).
