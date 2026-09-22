# AMD AMF Hardware-Encode Support — Implementation Report

## What changed

| File | Change |
|---|---|
| `src/logger.py` | Added `check_amf()` (mirrors `check_nvenc()`, checks FFmpeg `-encoders` for `h264_amf`). Updated `print_startup_banner()` to also report AMF availability. |
| `src/gpu_cpu_utils.py` | Imports `check_amf`; adds `AMF_AVAILABLE = check_amf()` next to `NVENC_AVAILABLE`. `GPU_AVAILABLE`/`USE_GPU`/CuPy path untouched. |
| `src/ffmpeg_processing.py` | Added `get_amf_quality_args()`. Updated all 4 call sites that previously did `elif use_nvenc: cmd.extend(get_nvenc_quality_args(...))` to dispatch by `gpu_encoder` family (NVENC vs. AMF). Also fixed the two decode-side `-hwaccel cuda` sites (`extract_clip_segment_ffmpeg`, `concatenate_videos_ffmpeg`) to gate CUDA decode hwaccel on the NVENC family specifically — see "Notable decision" below. Left the ProRes-preview `-hwaccel cuda` block and all other pre-existing `-hwaccel` logic alone. |
| `src/gui.py` | Imports `AMF_AVAILABLE`. Added `elif AMF_AVAILABLE:` branch to the Processing Mode radio (`AMD AMF H.264` / `AMD AMF HEVC (H.265)`), mirroring the NVENC branch and using a new `get_processing_mode_info_amf()`. Renamed the local `use_nvenc` variable in `_process_video_impl` to `use_hwenc` and broadened its computation to recognize AMF modes (per spec's explicit example), updating all downstream uses in that function (the `prepare_visual_sources` call, status/label text). Default-mode picker now falls back to `h264_amf` when NVENC isn't available but AMF is. |
| `src/ui_content.py` | Added `get_processing_mode_info_amf()` alongside the existing NVENC/CPU variants. |
| `src/video_processor.py` | **Not in the original file list, but required — see below.** Imports `AMF_AVAILABLE`; `create_music_video()`'s internal `use_nvenc` gate (which independently recomputes whether to hardware-encode) now recognizes both NVENC and AMF families, and — critically — no longer depends on `use_gpu`. Also de-hardcoded a "NVIDIA" string in a status print so it doesn't mislabel an AMD encode. |
| `README.md` | New "🟥 AMD AMF hardware encoding" subsection under "🔧 Fork Changes", matching the existing style; explicitly notes CuPy/analysis stays NVIDIA-only. |

`_to_delete/` was not touched. No files or functions were deleted.

## Deviation from the spec's file list: `src/video_processor.py`

The spec's "Files you'll touch" list didn't include `src/video_processor.py`, but two bugs there would have made the feature **completely non-functional** on the project owner's actual target machine if left alone, so I fixed them:

1. **`create_music_video()` recomputes its own `use_nvenc` flag internally**, independent of the flag `gui.py` computes. It was gated on `NVENC_AVAILABLE` only — AMF-mode renders would have silently fallen back to CPU encoding even though the GUI said "AMD AMF". Fixed by broadening the same family-check logic used in `gui.py`.
2. **That same internal flag was also gated on `use_gpu`**, which is `GPU_AVAILABLE` (CuPy/CUDA) set in `gui.py`. Per the task's own context, the project owner's AMD Radeon 780M has no CUDA, so `GPU_AVAILABLE`/`use_gpu` will always be `False` there — multiplying the hw-encode gate by `use_gpu` would have permanently disabled AMF regardless of the other fixes. I removed that dependency; hardware-encoder selection is now driven purely by `gpu_encoder` family + `NVENC_AVAILABLE`/`AMF_AVAILABLE`, decoupled from the CuPy analysis path (which stays exactly as scoped — CUDA-only, untouched).

I judged this safe under the "don't weaken NVENC" constraint: for an NVIDIA machine, `GPU_AVAILABLE` is essentially always `True` when NVENC is, so removing that factor is a no-op there (or a strict widening, not a narrowing) — it cannot disable NVENC in any case where it previously worked.

## Naming choice (step 3): kept `use_nvenc` in `ffmpeg_processing.py`/`video_processor.py` (option a)

I did **not** rename `use_nvenc` → `use_hwenc` inside `ffmpeg_processing.py`'s four functions or `video_processor.py`. Reasoning:

- `video_processor.py` has ~25 references to `use_nvenc` across CLI argument parsing, cache-key generation, worker-count throttling, and status printing, most of it unrelated to the render dispatch this task touches — a full rename there is exactly the "too many unrelated call sites, risks breaking something" case the spec calls out as the trigger for option (a).
- In `gui.py`, I *did* use `use_hwenc` as the local variable name, exactly as the spec's own example showed, since that's contained to one function (`_process_video_impl`) with a small number of downstream uses. Where it's passed into `video_processor.py`, it's passed under the keyword `use_nvenc=` to match that function's (unrenamed) parameter name.

Net effect: `use_nvenc` as a parameter name broadened in meaning to "use a hardware encoder" throughout `ffmpeg_processing.py`/`video_processor.py`, documented with a comment at the one place (`create_music_video`) where that's non-obvious; `gui.py` alone uses the clearer `use_hwenc` name locally.

## Notable decision: decode-side `-hwaccel cuda` stays NVENC-only

Two of the four call sites in `ffmpeg_processing.py` (`extract_clip_segment_ffmpeg`, `concatenate_videos_ffmpeg`) used the same `use_nvenc` flag for two different things: selecting the **encoder** quality-args AND selecting `-hwaccel cuda` for **decode**. Since `use_nvenc` now also means "AMF in use", broadening both uses of the flag uniformly would have forced NVIDIA's CUDA decode hwaccel onto AMD hardware. I split these: the quality-args dispatch broadens per the spec's instructions, but the `-hwaccel cuda` selection now explicitly checks `gpu_encoder in ('h264_nvenc','hevc_nvenc')`, so an AMF export falls through to the existing generic `-hwaccel auto` path instead (same as the CPU path already did). This mirrors the spirit of the spec's own explicit instruction to leave the GUI's ProRes-preview `-hwaccel cuda` block NVIDIA-only.

## Syntax check

```
python3 -c "
import ast
files = ['src/logger.py','src/gpu_cpu_utils.py','src/ffmpeg_processing.py','src/gui.py','src/video_processor.py','src/ui_content.py']
for f in files:
    ast.parse(open(f).read())
    print(f, 'OK')
"
```
All six touched Python files parsed cleanly (the spec asked to check the original four; I added `video_processor.py` and `ui_content.py` since I touched them too).

## Open questions / risks for the project owner to verify on the AMD box

There is no Windows/FFmpeg/AMD environment on this dev machine, so **none of this has been run against a real AMF encoder** — only reasoned through and syntax-checked. Please verify on the 780M box:

1. **`h264_amf`/`hevc_amf` actually appear in your FFmpeg build's `-encoders` output.** `check_amf()` does a literal substring match on `h264_amf`; confirm your gyan.dev/BtbN build was compiled with `--enable-amf`.
2. **The AMF flag set I used** (`-quality quality -rc vbr_peak -qp_i 18 -qp_p 20 -b:v 0 -usage transcoding`, plus `-profile:v high`/`main`) is a reasonable high-quality preset per AMF documentation, but I could not empirically tune or verify it — if output looks off (banding, bitrate spikes, rejected flags), that's the first place to check. `ffmpeg -h encoder=h264_amf` on your machine will show the authoritative flag list for your build.
3. **Decode-side hwaccel for AMF exports falls back to `-hwaccel auto`**, not an AMD-specific decode path (e.g. `d3d11va`). This was a deliberate scope decision (see above) but means clip-extraction decode won't be AMD-accelerated even though encode will — worth profiling if extraction is slower than expected.
4. **GUI radio-button behavior**: if your box ever has *both* an NVIDIA GPU (NVENC) and the AMD iGPU (AMF) active, the NVENC branch takes priority in the UI (`if NVENC_AVAILABLE: ... elif AMF_AVAILABLE: ...`) — AMF options won't be offered in that case. Confirm that's the behavior you want; the spec's own examples implied this priority order but didn't state it explicitly.
5. **First real render**: worth watching console output for the new `AMF: [OK]`/`[NO]` line in the startup banner and the `Encoder: ⚡ H264_AMF (GPU-accelerated)`-style status line during a render, to confirm the dispatch is actually landing on AMF and not silently falling back to CPU.
