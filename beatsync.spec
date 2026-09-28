# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for packaging BeatSync into a standalone onedir Windows distribution."""

import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Collect packages that have data files, DLLs, or dynamic imports
packages_to_collect = [
    'gradio',
    'gradio_client',
    'safehttpx',
    'jinja2',
    'uvicorn',
    'fastapi',
    'starlette',
    'librosa',
    '_soundfile_data',
    'onnxruntime',
    'cv2',
    'scipy',
    'PIL',
    'pydub',
    'yaml',
    'telemetry_parser',
    'groovy',
    'huggingface_hub',
]

for pkg in packages_to_collect:
    try:
        d, b, h = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)
    except Exception as e:
        print(f"Warning collecting {pkg}: {e}")

# Additional hidden imports for uvicorn and app modules
hiddenimports += [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'scipy.signal',
    'scipy.ndimage',
    'soundfile',
    'multiprocessing',
]

# Exclude large unnecessary things
excludes = [
    'tkinter',
    'matplotlib',
    'torch',
    'torchvision',
    'ultralytics',
    'cupy',
    'IPython',
    'notebook',
    'pytest',
]

a = Analysis(
    ['src/gui.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BeatSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BeatSync',
)
