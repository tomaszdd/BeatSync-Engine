import json
import glob
import os

plans = sorted(glob.glob(r"C:\BeatSyncTest\**\*.plan.json", recursive=True))
print(f"Details of clips < 0.5s:")
for p in plans:
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        clips = d.get("clips", [])
        if not clips and "selected_clips" in d:
            clips = d["selected_clips"]
        fname = os.path.basename(p)
        for i, c in enumerate(clips):
            dur = float(c.get("final_duration", c.get("duration", 0)))
            if 0 < dur < 0.5:
                src = c.get("source_name", "unknown")
                bbox = c.get("subject_bbox")
                cx = round((bbox[0] + bbox[2]) / 2, 3) if bbox else None
                print(f"  {fname[:35]} clip {i:02d}: dur={dur:.3f}s, src={src}, bbox_cx={cx}")
    except Exception as e:
        pass
