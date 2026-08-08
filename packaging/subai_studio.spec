# PyInstaller spec cho SubAI Studio.
# Build:  pyinstaller packaging/subai_studio.spec --noconfirm
#
# Sinh ra thư mục dist/SubAIStudio/ chạy độc lập (không cần cài Python).
# Model AI KHÔNG được nhúng - chúng tự tải về models_cache/ ở lần chạy đầu.

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent

hidden = [
    "faster_whisper",
    "demucs",
    "TTS",
    "torch",
    "torchaudio",
    "soundfile",
    "yt_dlp",
]

a = Analysis(
    [str(ROOT / "run_desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubAIStudio",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SubAIStudio",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SubAI Studio.app",
        icon=None,
        bundle_identifier="com.subai.studio",
    )
