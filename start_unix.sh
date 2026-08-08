#!/usr/bin/env bash
# Khởi động SubAI Studio trên Linux/macOS: tự tạo venv, tự cài thư viện, tự mở app.
#   chmod +x start_unix.sh && ./start_unix.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "=========================================================="
echo "   SubAI Studio - Khởi động"
echo "=========================================================="
echo

# ---------- Tìm Python 3.11 ----------
PYEXE=""
for candidate in python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYEXE="$candidate"
        break
    fi
done

if [ -z "$PYEXE" ]; then
    echo "[LỖI] Không tìm thấy Python trên máy này."
    echo "      Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    exit 1
fi

echo "Dùng Python: $PYEXE ($("$PYEXE" --version 2>&1))"
echo

# ---------- Tạo venv nếu chưa có ----------
if [ ! -x "venv/bin/python" ]; then
    echo "[1/3] Đang tạo môi trường ảo (venv)..."
    "$PYEXE" -m venv venv
    echo "      Xong."
    echo
fi

VPY="venv/bin/python"

# ---------- Cài thư viện nếu thiếu ----------
if ! "$VPY" -c "import PySide6" >/dev/null 2>&1; then
    echo "[2/3] Đang cài thư viện giao diện (lần đầu mất vài phút, ~150MB)..."
    "$VPY" -m pip install --upgrade pip
    "$VPY" -m pip install -r requirements-desktop.txt
    echo "      Xong."
    echo
fi

# ---------- Mở app ----------
echo "[3/3] Đang mở SubAI Studio..."
echo
if ! "$VPY" run_desktop.py; then
    echo
    echo "=========================================================="
    echo "   CÓ LỖI XẢY RA - chạy lệnh sau để biết thiếu gì:"
    echo "      venv/bin/python check_setup.py"
    echo "=========================================================="
    exit 1
fi
