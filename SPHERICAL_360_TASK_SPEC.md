# Task: Preserve-360 output mode (no dewarping — that's a separate future feature)

## Goal
Add an opt-in "source is 360°/equirectangular" mode so BeatSync can beat-sync-cut and
concatenate 360 GoPro/Insta360 footage and produce an output file that is STILL a valid
360 video (correct spherical metadata), instead of being treated as flat video and
scaled/cropped into a distorted rectangle.

**Explicitly out of scope**: dewarping / reframing 360 footage down to a flat rectilinear
crop. That's a separate, bigger future feature (candidate prior art already identified:
github.com/stechdrive/Insta360Convert-GUI extracts pitch/yaw/FOV perspective views from
equirectangular video — useful reference when that feature is scoped later, don't build
it now).

## Background
- Repo: this fork of xpix/BeatSync-Engine, an AI beat-synced video editor. Analyzes music,
  selects/cuts source video clips to the beat, concatenates them with the audio track.
- Currently 100% assumes flat rectilinear source video. No 360/equirectangular handling
  anywhere (verified via grep — nothing for "360", "equirect", "spherical", "fisheye").
- Final assembly happens in `src/ffmpeg_processing.py`, function `concatenate_videos_ffmpeg`
  (~line 746) — this is where the final output file is muxed (video+audio combined,
  `-c:v copy` for the prores/lossless path). This is the right point to inject spherical
  metadata into the finished container, since it needs to happen once on the final file,
  not per-clip.
- GPU-encoder flag (`--gpu-encoder`) is threaded CLI → `video_processor.py` → GUI
  (`gui.py`) → `ffmpeg_processing.py`. Follow the same threading pattern for a new
  `--360` / "Source is 360°" flag.

## What to build
1. **Flag plumbing**: `--360` CLI flag (video_processor.py argparse) + GUI checkbox in
   gui.py ("Source is 360° / equirectangular — keep spherical, don't crop"), threaded
   down to ffmpeg_processing.py the same way gpu_encoder is.
2. **Skip flat-video framing when 360 is set**: when the flag is on, any aspect-ratio
   crop/letterbox/16:9-force logic (see `scale=...force_original_aspect_ratio` calls in
   ffmpeg_processing.py) must NOT run — equirectangular source is 2:1 and must pass
   through at full frame, uncropped. Verify no existing crop/letterbox step silently
   still applies when this flag is set.
3. **Spherical metadata injection on the final output**: after `concatenate_videos_ffmpeg`
   produces the output file, inject proper Spherical Video V2 metadata (the format
   YouTube/VR players/Google's spec expect) into the MP4/MOV container. Research the
   correct approach — options to evaluate:
   - Shell out to the `spatialmedia` pip package (Google's own spatial-media metadata
     injector) if it can be added as a dependency and works headless/non-interactively.
   - Hand-roll injection of the `uuid` box with the spherical XML if the above isn't
     viable (there are documented open-source examples of the box format).
   Pick whichever is more reliable and document the choice and why in the report.
4. **Verify the metadata actually sticks**: after injection, read it back (via the same
   tool in read-mode, or a metadata parser) and confirm the box round-trips correctly.
   If possible, also confirm via `ffprobe`/`exiftool` that the file is recognized as
   spherical.
5. **Must not regress the existing flat pipeline** — flag defaults to off/False
   everywhere; behavior for all existing (non-360) use must be byte-for-byte unchanged.

## Testing requirement (real hardware, real footage — do not skip)
Per this repo's established lesson (see git log / AMD_AMF_REPORT.md history): syntax
review is not enough, CAO's own prior report on this repo was correct to flag "cannot
verify without a real run" and that mattered — a real bug (`-hwaccel auto` DXVA2 crash)
was only found by actually rendering. For this task:
- Test on the UM890 (`ssh um890`, AMD Radeon 780M box this repo is verified against).
- Need a real equirectangular 360 test file. Check `D:\Photos\360 Photos & Videos\GoPro Max\`
  on the UM890 for existing GoPro Max footage first. If those are raw dual-fisheye `.360`
  files rather than already-stitched equirectangular MP4s, flag that clearly in the report
  rather than guessing — stitching is a separate prerequisite this task should NOT attempt
  to solve, just note if it's blocking a real test.
- Run both the CLI path and (at least) `gui.py`'s underlying `process_video()` function
  directly, same as prior verification in this repo's history.
- Confirm final output: (a) is uncropped/full equirect frame, (b) has valid spherical
  metadata that reads back correctly, (c) plays back as a normal (if unlabeled-in-player)
  video — i.e. it isn't corrupted.

## Deliverable
- Implementation, committed.
- Written report (like prior `AMD_AMF_REPORT.md` in this repo) stating exactly what was
  tested, what passed, and honestly flagging anything not verified (e.g. if no real
  equirect test file was available, say so explicitly rather than claiming full
  verification).
