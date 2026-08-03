#!/usr/bin/env bash
# Cài đặt + khởi chạy ứng dụng chỉ bằng 1 lệnh:  ./run.sh
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "==> Tạo môi trường ảo..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Cài đặt thư viện..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "!! Đã tạo file .env — hãy mở ra và điền DEEPGRAM_API_KEY (hoặc GROQ_API_KEY),"
  echo "!! sau đó chạy lại ./run.sh"
  exit 1
fi

echo "==> Khởi chạy tại http://localhost:${PORT:-7860}"
exec python app.py
