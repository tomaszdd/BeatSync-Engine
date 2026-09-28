# Task: package BeatSync as a standalone Windows exe, deploy + test on the PH Plex box

## Goal
Produce a standalone distributable of this app (no separate Python/git install required on
the target machine) and get it actually running with a reachable web GUI on the PH Plex box
(`ssh phmedia` -> `DESKTOP-NLNSBOD`, `172.30.3.229`, Windows). Report back the working GUI
URL when done.

## Real constraints, already confirmed — don't rediscover these
- PH Plex box's GPU is an **NVIDIA GeForce 9400 GT** (2009-era, no NVENC support — NVENC
  didn't exist on cards this old). This app's existing `check_nvenc()`/`check_amf()`
  (`src/gui.py`) already do a real hardware probe (not just a compiled-codec-list grep — see
  this repo's own history, `4129856`/`84ad20e`), so it should correctly detect no usable
  hardware encoder here and fall back to CPU/ProRes-only in the Processing Mode picker. Don't
  add new code for this — just confirm the probe behaves correctly on real hardware once
  deployed, and set expectations: renders on this box will be CPU-only and slower than
  `um890`'s AMD AMF path.
- PH Plex box has **no Python and no git** installed (confirmed). That's fine — the whole
  point of a standalone exe is not needing either on the target. Don't install them there
  unless you decide the build itself needs to happen on that box (see below).
- `C:\ffmpeg` already exists on the PH Plex box (used by its existing FileBot/Prowlarr setup)
  — check what's actually in it before assuming it's usable for this app (this app expects
  `ffmpeg.exe`/`ffprobe.exe` at a specific bundled relative path, see `src/logger.py`'s
  `ROOT_DIR/bin/ffmpeg/`).
- The **known-working environment** is `um890` (`ssh um890`, AMD box) —
  `C:\BeatSyncTest\app\BeatSync-Engine-main\venv` already has every Python dependency
  installed and verified against real renders (this repo's whole commit history). Building
  the PyInstaller package FROM that venv (rather than a fresh checkout) is the lower-risk
  path — it reuses a proven dependency set instead of re-resolving one from scratch. Do the
  actual PyInstaller build run on a real Windows box (`um890` or the PH Plex box itself, your
  call) — don't try to cross-compile a Windows exe from Linux/Jarvis, it doesn't work
  reliably for this kind of app (native deps, ffmpeg subprocess paths, etc.).

## What to build
- PyInstaller, almost certainly `--onedir` not `--onefile` — this app shells out to bundled
  `ffmpeg.exe`/`ffprobe.exe` and reads asset files (`assets/fonts/`, theme presets) at known
  relative paths; a onedir output next to those files is far less fragile than trying to
  unpack a single exe's temp dir correctly for subprocess calls. Verify this judgment against
  what you actually find in the code rather than assuming.
- Entry point: `src/gui.py` (same thing `Launch BeatSync.bat` on `um890` already runs).
- Bundle `ffmpeg.exe`/`ffprobe.exe` from `um890`'s known-working copy
  (`C:\BeatSyncTest\app\BeatSync-Engine-main\bin\ffmpeg\`), not whatever's in the PH Plex
  box's own unrelated `C:\ffmpeg`.
- **Leave out the Qwen/llama.cpp Layer 2 semantic-scoring model files**
  (`D:\BeatSync-Models\` on `um890`, ~2.5GB) for this first deploy — the 9400 GT has nowhere
  near the compute for that Vulkan inference path to be usable, and it's a multi-GB download
  for a feature that would be pointless-to-broken on this hardware. The app already degrades
  gracefully without it (confirmed working behavior throughout this repo's history — Layer 2
  is optional, Layer 1 heuristic scoring works standalone). If you disagree after checking the
  actual code, explain why in the report rather than silently deviating.
- Bundle `assets/fonts/` (title-theme typography — real bug risk if left out, themed title
  cards will silently render with wrong fonts, not error).

## Deploy + verify
- Copy the built onedir output to the PH Plex box, e.g. `C:\BeatSync\` (check available drive
  space/letters there first, don't assume `D:` exists the way it does on `um890`).
- Launch it there (foreground first to see any startup errors, per this repo's own documented
  gotcha: `Start-Process`-based redirection has silently produced 0-byte logs for long-lived
  Windows processes over SSH before — run it directly via the SSH session with a timeout, per
  that same gotcha's documented workaround).
- Confirm the Gradio GUI actually comes up and is reachable **from another machine**, not just
  `localhost` on the Plex box itself (the code binds `0.0.0.0:7860`, confirmed in `gui.py`) —
  `curl http://172.30.3.229:7860/` from Jarvis or `um890` after launching.
- Confirm the Processing Mode picker on this box actually shows CPU/ProRes only (no NVENC/AMF
  wrongly offered) — same false-positive class of bug this repo already found once before
  (`4129856`) on different hardware; don't assume it's fine, check the live `/config` the way
  prior work in this repo did.
- Don't set up autostart/persistence (systemd-equivalent, scheduled task) — out of scope for
  this pass, just get it running and verified once. Note in your report if you think that's a
  sensible near-term follow-up, but don't build it now.

## Constraints
- Working directory: `/home/pi/projects/BeatSync-Engine` on Jarvis; real hardware access via
  `ssh um890` and `ssh phmedia`.
- Don't delete anything on the PH Plex box without listing it and asking first — you don't
  know what else lives on that machine (it's a shared FileBot/Prowlarr/qBittorrent box, see
  this repo's sibling project notes).
- Don't touch `CLAUDE.md`/`AGENTS.md`.
- Write `PH_PLEX_EXE_DEPLOY_REPORT.md`, commit anything code-relevant (the PyInstaller spec
  file if you create one, any small code fixes needed to make packaging work), push, and paste
  real `git status`/`git log origin/main..HEAD` output as proof — this repo's history shows
  CAO workers have repeatedly claimed "committed and pushed" before it was true.
- End the report with the exact URL Tomasz should open to reach the working GUI.
