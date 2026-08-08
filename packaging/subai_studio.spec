# PyInstaller spec cho SubAI Studio.
#
#   pyinstaller packaging/subai_studio.spec --noconfirm
#
# Tương đương --onedir --windowed --name SubAIStudio, kèm sẵn --collect-all cho
# toàn bộ thư viện AI nặng nên không cần gõ lại chuỗi flag dài. Package nào chưa
# cài thì được bỏ qua, build vẫn chạy (bản chỉ-phụ-đề không cần TTS chẳng hạn).
#
# Model AI KHÔNG được nhúng sẵn - chúng tự tải về models_cache/ ở lần chạy đầu.
# Nếu muốn đóng gói kèm model đã tải, tạo thư mục models_cache/ ở gốc dự án
# trước khi build; spec sẽ tự phát hiện và đưa vào.

import importlib.util
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH).parent

# --collect-all cho từng package: kéo cả file dữ liệu, .so/.dll và submodule ẩn.
COLLECT_PACKAGES = [
    "torch",
    "torchaudio",
    "demucs",
    "faster_whisper",
    "TTS",
    "pyrubberband",
    "soundfile",
    "yt_dlp",
    "pydantic",
]

datas = []
binaries = []
hiddenimports = []
missing = []

for package in COLLECT_PACKAGES:
    if importlib.util.find_spec(package) is None:
        missing.append(package)
        continue
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
    hiddenimports.append(package)

if missing:
    print(f"[subai] Bỏ qua package chưa cài: {', '.join(missing)}")

models_cache = ROOT / "models_cache"
if models_cache.is_dir():
    datas.append((str(models_cache), "models_cache"))
    print("[subai] Đóng gói kèm models_cache/")

a = Analysis(
    [str(ROOT / "run_desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    console=False,          # --windowed
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SubAIStudio",     # --onedir --name SubAIStudio
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="SubAI Studio.app",
        icon=None,
        bundle_identifier="com.subai.studio",
    )
