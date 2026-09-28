#!/usr/bin/env python3
"""Build and bundle standalone Windows distributable for BeatSync."""

import os
import sys
import shutil
import subprocess

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_command(cmd, cwd=ROOT_DIR):
    print(f"[*] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=True)
    return result


def main():
    print("=" * 60)
    print("Building BeatSync standalone Windows distribution")
    print(f"Root: {ROOT_DIR}")
    print("=" * 60)

    # 1. Run PyInstaller
    spec_path = os.path.join(ROOT_DIR, "beatsync.spec")
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spec file not found at: {spec_path}")

    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller", "--clean", "-y", spec_path]
    run_command(pyinstaller_cmd)

    dist_dir = os.path.join(ROOT_DIR, "dist", "BeatSync")
    exe_path = os.path.join(dist_dir, "BeatSync.exe")
    if not os.path.exists(exe_path):
        raise RuntimeError(f"Build failed: {exe_path} not found")

    print(f"\n[+] PyInstaller build complete: {exe_path}")

    # 2. Bundle ffmpeg and ffprobe
    ffmpeg_src_dir = os.path.join(ROOT_DIR, "bin", "ffmpeg")
    ffmpeg_dest_dir = os.path.join(dist_dir, "bin", "ffmpeg")
    os.makedirs(ffmpeg_dest_dir, exist_ok=True)
    for bin_name in ["ffmpeg.exe", "ffprobe.exe"]:
        src = os.path.join(ffmpeg_src_dir, bin_name)
        dst = os.path.join(ffmpeg_dest_dir, bin_name)
        if os.path.exists(src):
            print(f"[*] Copying {bin_name} -> {dst}")
            shutil.copy2(src, dst)
        else:
            print(f"⚠️ Warning: {src} not found!")

    # 3. Bundle ONNX model (yolov8n.onnx)
    models_src_dir = os.path.join(ROOT_DIR, "bin", "models")
    models_dest_dir = os.path.join(dist_dir, "bin", "models")
    os.makedirs(models_dest_dir, exist_ok=True)
    yolo_model = os.path.join(models_src_dir, "yolov8n.onnx")
    if os.path.exists(yolo_model):
        print(f"[*] Copying yolov8n.onnx -> {models_dest_dir}")
        shutil.copy2(yolo_model, os.path.join(models_dest_dir, "yolov8n.onnx"))

    # 4. Bundle assets (fonts and watermark)
    assets_src_dir = os.path.join(ROOT_DIR, "assets")
    assets_dest_dir = os.path.join(dist_dir, "assets")
    os.makedirs(assets_dest_dir, exist_ok=True)

    fonts_src = os.path.join(assets_src_dir, "fonts")
    fonts_dst = os.path.join(assets_dest_dir, "fonts")
    if os.path.exists(fonts_src):
        print(f"[*] Copying fonts -> {fonts_dst}")
        if os.path.exists(fonts_dst):
            shutil.rmtree(fonts_dst)
        shutil.copytree(fonts_src, fonts_dst)

    watermark_src = os.path.join(assets_src_dir, "tdd_watermark.png")
    if os.path.exists(watermark_src):
        print(f"[*] Copying watermark -> {assets_dest_dir}")
        shutil.copy2(watermark_src, os.path.join(assets_dest_dir, "tdd_watermark.png"))

    # 5. Create runtime input and output directories
    for sub in [
        os.path.join(dist_dir, "input", "audio"),
        os.path.join(dist_dir, "input", "video"),
        os.path.join(dist_dir, "output"),
    ]:
        os.makedirs(sub, exist_ok=True)

    print("\n" + "=" * 60)
    print("Standalone distribution assembled successfully:")
    print(f"Location: {dist_dir}")
    print("Contents:")
    for root, dirs, files in os.walk(dist_dir):
        rel = os.path.relpath(root, dist_dir)
        if rel == ".":
            for f in files[:10]:
                print(f"  {f}")
        elif rel in ["bin", "bin\\ffmpeg", "bin\\models", "assets", "assets\\fonts"]:
            print(f"  {rel}/ ({len(files)} files)")
    print("=" * 60)


if __name__ == "__main__":
    main()
