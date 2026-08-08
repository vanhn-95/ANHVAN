# SubAI Studio — Desktop App Lồng Tiếng & Phụ Đề AI

Ứng dụng desktop (Windows / Linux / macOS) tự động hoá toàn bộ quy trình bản địa hoá
video: tải video → tách giọng khỏi nhạc nền → trích xuất phụ đề → dịch AI → lồng tiếng
nhái giọng gốc → render video hoàn chỉnh. Tất cả chạy trong một cửa sổ, không cần gõ lệnh.

![Giao diện](docs/screenshot-job.png)

## 🌟 Tính Năng

| Tính năng | Công nghệ |
|---|---|
| Tải video đa nền tảng (YouTube, TikTok, Douyin, Bilibili…) | `yt-dlp` |
| Tách vocal / nhạc nền để ASR chính xác hơn | Demucs HTDemucs v4 |
| Trích xuất phụ đề tốc độ cao, lọc khoảng lặng | Faster-Whisper + Silero VAD |
| Dịch giữ văn phong, không lệch số dòng | Gemini 2.5 Flash qua Proxy Server |
| Lồng tiếng nhái giọng nhân vật gốc, khớp mốc thời gian | XTTS-v2 + time-stretch |
| Auto-ducking: hạ nhạc nền khi có lời thoại | FFmpeg `sidechaincompress` |
| Khoá bản quyền theo máy | HWID + chữ ký RSA-PSS |

Giao diện gồm 4 tab: **Xử lý video**, **Tuỳ chỉnh nâng cao**, **Môi trường** (báo engine nào
đã sẵn sàng, engine nào thiếu và lệnh cài), **Bản quyền** (HWID + license key).

## 🛠️ Cài Đặt

### Yêu cầu
- **OS**: Windows 10/11 64-bit, Ubuntu 22.04+, hoặc macOS 12+
- **Python**: 3.11 (bắt buộc — Coqui TTS chưa hỗ trợ 3.12+)
- **GPU**: NVIDIA ≥ 6GB VRAM + CUDA 12.1 (chạy CPU vẫn được nhưng rất chậm)
- **Bắt buộc**: FFmpeg trong PATH

### Cài nhanh

```bash
git clone https://github.com/vanhn-95/anhvan.git
cd anhvan

python3.11 -m venv venv         # Windows: py -3.11 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# PyTorch bản CUDA (bỏ qua nếu chỉ chạy CPU)
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121

pip install -r requirements.txt

cp .env.example .env            # rồi điền GEMINI_API_KEY nếu chạy proxy trên máy này
```

Chỉ muốn mở giao diện để xem trước, chưa cài engine AI nặng:

```bash
pip install -r requirements-desktop.txt
```

App vẫn mở bình thường — tab **Môi trường** sẽ chỉ rõ thiếu gì và cần cài lệnh nào.

📖 Hướng dẫn đầy đủ từng bước (FFmpeg, Rubber Band, `.env`, build `.exe`, các lỗi hay
gặp): **[docs/SETUP.md](docs/SETUP.md)**.

## 🚀 Sử Dụng

### 1. Chạy Proxy Server dịch thuật

API key Gemini chỉ nằm ở server, client không bao giờ giữ key.

```bash
export GEMINI_API_KEY="YOUR_KEY"
export SUBAI_LICENSES="key1,key2"      # tuỳ chọn: giới hạn client được phép gọi
uvicorn server.proxy_server:app --host 0.0.0.0 --port 8000
```

Hoặc bằng Docker:

```bash
docker build -t subai-proxy .
docker run -p 8000:8000 -e GEMINI_API_KEY="YOUR_KEY" subai-proxy
```

### 2. Mở app desktop

```bash
python run_desktop.py           # hoặc: python -m desktop
```

Dán URL (hoặc chọn file) → chọn ngôn ngữ đích → tick các bước cần chạy → **Bắt đầu xử lý**.
Tiến độ, log từng bước và nút **Dừng** nằm ngay dưới cùng cửa sổ.

Kết quả trong thư mục xuất:

```
<tên>.origin.srt          # phụ đề gốc
<tên>.vi.srt              # phụ đề đã dịch
<tên>.vi.dubbed.mp4       # video đã lồng tiếng (hoặc .sub.mp4 nếu chỉ làm phụ đề)
```

### 3. Chạy bằng dòng lệnh (tuỳ chọn)

```bash
python -m src.main_pipeline "https://youtu.be/xxxx" -t vi -o ~/SubAI/output
python -m src.main_pipeline video.mp4 --no-dub --burn      # chỉ phụ đề, ghi chết vào video
```

## 🧱 Kiến Trúc

```
desktop/     Giao diện PySide6 (app, cửa sổ chính, worker thread, theme, env check)
src/         Pipeline: downloader → separator → ASR → translator → TTS → composer
server/      FastAPI proxy giữ API key Gemini
tools/       Công cụ phát hành license (keygen / issue)
packaging/   PyInstaller spec để build bản .exe / .app
```

Pipeline chạy trong `QThread` riêng, giao tiếp với UI qua `ProgressReporter` → Qt signals,
nên cửa sổ không bao giờ bị đơ và có thể huỷ giữa chừng. Mọi engine AI được **import lazy**:
thiếu engine nào thì chỉ bước đó bị tắt, app vẫn chạy. Chi tiết: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 🧪 Test

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen pytest
```

## 📦 Đóng Gói & Bảo Mật

Build bản chạy độc lập (spec đã kèm sẵn `--collect-all` cho toàn bộ thư viện AI nên
không dính `ModuleNotFoundError` lúc chạy file build):

```bash
pip install pyinstaller
pyinstaller packaging/subai_studio.spec --noconfirm
# -> dist/SubAIStudio/
```

Phát hành license theo máy:

```bash
python tools/license_tool.py keygen --out keys/
python tools/license_tool.py issue --key keys/private.pem \
    --hwid <HWID khách gửi> --customer "Tên khách" --expires 2027-01-01
```

Nhúng public key vào bản build client qua biến môi trường `SUBAI_PUBLIC_KEY`, và tắt chế
độ dev bằng `SUBAI_DEV_MODE=0`. Khi cần khoá chặt hơn:

```bash
cythonize -3 -i src/security_guard.py          # biên dịch module bảo mật sang C
pyarmor gen --output dist_protected src/*.py   # obfuscate mã nguồn
```

## 📄 License

Phát triển và sở hữu bởi SubAI Team. Sao chép thương mại cần license key do hệ thống phát hành.
