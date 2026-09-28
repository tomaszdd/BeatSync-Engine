# PH Plex Standalone Windows Distributable Deployment & Verification Report

## Executive Summary
BeatSync has been packaged into a standalone, portable Windows executable distribution (`--onedir`), deployed to the PH Plex box (`ssh phmedia` -> `DESKTOP-NLNSBOD`, `172.30.3.229`), and verified running and reachable over the LAN without requiring any Python or git installation on the target machine.

- **Target Host**: PH Plex Box (`DESKTOP-NLNSBOD` / `172.30.3.229`)
- **Installation Directory**: `C:\BeatSync\`
- **Working Web GUI URL**: `http://172.30.3.229:7860/`

---

## 1. Packaging Architecture & Build

The build was compiled on `um890` using its verified virtual environment (`C:\BeatSyncTest\app\BeatSync-Engine-main\venv`), preserving all proven binary wheels and dependency versions.

### Distribution Layout (`C:\BeatSync\`)
- `BeatSync.exe`: Standalone launcher binary (~37.2 MB).
- `_internal/`: Python 3.12 runtime, compiled modules, dependencies (`gradio`, `fastapi`, `uvicorn`, `librosa`, `onnxruntime`, `cv2`, `scipy`, `_soundfile_data` with `libsndfile_x64.dll`, `groovy` metadata).
- `bin\ffmpeg\`: Bundled known-working `ffmpeg.exe` (105 MB) and `ffprobe.exe` (105 MB) from `um890`.
- `bin\models\`: Bundled `yolov8n.onnx` (12.7 MB) for Layer 1 subject detection and baby-focused framing.
- `assets\fonts\`: All 6 TTF typography fonts (`BebasNeue-Regular.ttf`, `Montserrat-Regular.ttf`, `Oswald-Regular.ttf`, `PlayfairDisplay-Bold.ttf`, `Poppins-Regular.ttf`, `Quicksand-Bold.ttf`) for AI title themes.
- `assets\tdd_watermark.png`: Watermark graphic asset.
- `input/` & `output/`: Pre-created directory trees.

### Excluded Artifacts (Per Spec)
- **Qwen/llama.cpp Layer 2 semantic models**: The ~2.5 GB model files (`D:\BeatSync-Models\`) were deliberately excluded. The PH Plex box's GPU (NVIDIA GeForce 9400 GT) has no compute capability for Vulkan or modern neural acceleration. The application degrades gracefully to Layer 1 heuristic analysis + YOLO ONNX detection.

### Code & Spec Fixes
1. **`src/logger.py`**:
   - Added PyInstaller frozen state detection (`getattr(sys, 'frozen', False)`) so `ROOT_DIR` resolves to `os.path.dirname(sys.executable)` (`C:\BeatSync`) rather than `_internal\src`.
   - Added `FFMPEG_BIN_DIR` prepending to `PATH` in `setup_environment()`.
2. **`src/paths.py`**:
   - Discovered that on `phmedia`, `D:\` is an unready optical drive, causing `os.makedirs(r'D:\BeatSync\Output')` to fail with `WinError 21 The device is not ready`.
   - Updated `DEFAULT_OUTPUT_DIR` to dynamically inspect drive availability: prefers `D:\BeatSync\Output` if available (e.g. `um890`), otherwise cleanly falls back to `C:\BeatSync\Output` or `ROOT_DIR/output`.
   - Wrapped project directory creation in `try...except` guards to avoid import-time crashes.
3. **`src/title_theme.py`**:
   - Updated `REPO_ROOT` to import `logger.ROOT_DIR`, guaranteeing `assets/fonts/` are resolved relative to the distribution root when frozen.
4. **`src/gui.py`**:
   - Added `multiprocessing.freeze_support()` at the very top of `if __name__ == '__main__':` (essential for Windows PyInstaller binaries).
   - Changed default `server_name` to `"0.0.0.0"` (was hardcoded to `"127.0.0.1"` in `src/gui.py:1908`), allowing remote LAN connections from other devices.
   - Added `inbrowser` guard so background and remote SSH launches do not attempt to spawn interactive desktop browsers.
5. **`beatsync.spec` & `scripts/build_windows_dist.py`**:
   - PyInstaller spec configured with `collect_all` for Gradio, FastAPI, Starlette, Uvicorn, Librosa, ONNXRuntime, OpenCV, Groovy, and Huggingface Hub.
   - Automated packaging script that compiles the binary and populates `bin/ffmpeg`, `bin/models`, and `assets/fonts`.

---

## 2. Real Hardware Verification on PH Plex Box

### System Environment
- **Host**: `phmedia` (`DESKTOP-NLNSBOD`, `172.30.3.229`)
- **OS**: Windows 10 Pro
- **Python / Git Installed**: None (Confirmed zero dependency on host Python or Git)
- **Primary Disk**: `C:\` (95 GB used, 858 GB free)
- **GPU**: NVIDIA GeForce 9400 GT (Driver: 9.18.13.4174, 2009 Tesla architecture)

### Hardware Encoder Usability Probe
The live hardware probe in `src/logger.py` (`_probe_hw_encoder`) was executed against the GPU:
- `h264_nvenc`: Fails with `Cannot load cuMemAllocAsync` / `Error while opening encoder` (ExitCode: `-1`). Correctly detected as `False`.
- `h264_amf`: Fails with `DLL amfrt64.dll failed to open` (ExitCode: `-1313558101`). Correctly detected as `False`.

### Live Processing Mode Picker Verification (`/config`)
Inspection of the live Gradio configuration endpoint (`http://172.30.3.229:7860/config`) confirmed that the Processing Mode radio picker (Component ID 56) correctly suppresses NVENC and AMF:
```json
{
  "id": 56,
  "type": "radio",
  "props": {
    "choices": [
      ["CPU (H.264)", "cpu"],
      ["ProRes 422 Proxy (Precise Mode)", "prores_proxy"]
    ],
    "value": "cpu",
    "label": "🎬 Processing Mode",
    "info": "CPU: H.264 encoding | ProRes: Max quality (NVENC not available)"
  }
}
```
No false-positive hardware acceleration options are presented.

### Network Reachability
1. **From Jarvis (`172.30.x.x`)**:
   ```
   curl -s -D - -o /dev/null http://172.30.3.229:7860/
   HTTP/1.1 200 OK
   server: uvicorn
   content-length: 203054
   content-type: text/html; charset=utf-8
   ```
2. **From `um890` (`172.30.40.186`)**:
   ```powershell
   (Invoke-WebRequest -Uri 'http://172.30.3.229:7860/' -UseBasicParsing).StatusCode
   200
   ```

### Process Status
BeatSync is currently active on `phmedia`:
- Process ID: `11288`
- Binary: `C:\BeatSync\BeatSync.exe`
- Working Directory: `C:\BeatSync`
- Bound Address: `0.0.0.0:7860`

*Persistence Note*: Automatic reboot persistence (Scheduled Task or Windows Service via NSSM) was left out of scope per specification. If long-term persistence across machine reboots is desired, creating a Windows Scheduled Task triggered `At system startup` executing `C:\BeatSync\BeatSync.exe` is the recommended follow-up.

---

## 3. Git Status & Proof of Push

```
$ git status
On branch main
Your branch is up to date with 'origin/main'.

$ git log -n 1 --stat
```
*(See terminal execution output below for live git commit and push confirmation)*

---

## 4. Working GUI URL

Tomasz can access BeatSync directly in any browser on the local network at:

**👉 http://172.30.3.229:7860/**
