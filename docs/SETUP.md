# Hướng Dẫn Cài Đặt & Build SubAI Studio

> **Phiên bản Python**: dùng **3.10 hoặc 3.11**. Coqui `TTS` chưa hỗ trợ Python 3.12+,
> nên cài trên 3.12 sẽ hỏng bước lồng tiếng (các bước còn lại vẫn chạy).

---

## Bước 1 — Môi trường ảo & dependencies

Không cài bằng `root` hay Python toàn cục: PyInstaller sẽ gom nhầm thư viện hệ thống
vào bản build.

```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# PyTorch bản CUDA 12.1 - phải cài TRƯỚC để pip không kéo về bản CPU
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu121

# Toàn bộ thư viện còn lại
pip install -r requirements.txt
```

Thứ tự này đúng: `requirements.txt` có ghi `torch>=2.1.0`, nhưng pip thấy torch đã cài
đủ điều kiện nên **không** thay bằng bản CPU.

Chỉ muốn mở giao diện xem trước (không cần GPU, tải ~150MB thay vì ~3GB):

```bash
pip install -r requirements-desktop.txt
```

---

## Bước 2 — Công cụ hệ thống

### FFmpeg — **bắt buộc**

Thiếu FFmpeg là hỏng mọi bước xử lý audio/video.

```powershell
# Windows
winget install --id Gyan.FFmpeg
```

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg
```

Sau khi cài trên Windows phải **mở lại terminal** để PATH cập nhật. Kiểm tra bằng
`ffmpeg -version`.

### Rubber Band — **tuỳ chọn**

Dùng để tăng tốc giọng đọc mà giữ nguyên cao độ. **Thiếu cũng không sao**: app tự chuyển
sang `atempo` của FFmpeg, chất lượng thấp hơn một chút nhưng vẫn khớp thời lượng.

```bash
# Ubuntu / Debian
sudo apt install rubberband-cli
pip install pyrubberband
```

Trên Windows **không có package `rubberband` trong winget** (thử `winget search rubberband`
sẽ không ra kết quả). Muốn dùng thì tải binary tại <https://breakfastquay.com/rubberband/>
rồi thêm vào PATH, hoặc build qua `vcpkg install rubberband[cli]`.

Cần **cả hai**: module Python `pyrubberband` **và** binary `rubberband` trong PATH. Tab
**Môi trường** báo rõ đang thiếu cái nào.

---

## Bước 3 — Cấu hình `.env`

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Điền vào `.env`:

```env
GEMINI_API_KEY="dien_api_key_cua_ban_vao_day"
SUBAI_PROXY_URL="http://127.0.0.1:8000"
```

**Quan trọng — key này là của *server*, không phải của app desktop.** App desktop không
bao giờ gọi thẳng Gemini; nó gửi câu thoại đến Proxy Server, và chỉ tiến trình chạy
`uvicorn server.proxy_server:app` mới đọc `GEMINI_API_KEY`. Chạy server trên cùng máy thì
một file `.env` ở gốc dự án phục vụ được cả hai.

Các biến `.env` mà app đọc:

| Biến | Dùng ở đâu | Ý nghĩa |
|---|---|---|
| `GEMINI_API_KEY` | Server | API key Gemini |
| `GEMINI_MODEL` | Server | Mặc định `gemini-2.5-flash` |
| `SUBAI_LICENSES` | Server | Danh sách license được phép gọi, cách nhau dấu phẩy |
| `SUBAI_PROXY_URL` | Client | Địa chỉ proxy mặc định trong app |
| `SUBAI_LICENSE_KEY` | Client | License key điền sẵn |
| `SUBAI_OUTPUT_DIR` | Client | Thư mục xuất mặc định |
| `SUBAI_DEV_MODE` | Client | `0` để bật kiểm tra bản quyền ở bản thương mại |
| `SUBAI_PUBLIC_KEY` | Client | Public key RSA để verify license |

Chưa có API key thì app vẫn chạy bình thường, chỉ riêng bước dịch báo lỗi không kết nối
được proxy.

Chạy server:

```bash
uvicorn server.proxy_server:app --host 0.0.0.0 --port 8000
```

---

## Bước 4 — Chạy thử trước khi build

Cả ba lệnh sau đều mở cùng một cửa sổ:

```bash
python run_desktop.py           # khuyến nghị
python -m desktop               # tương đương
python -m desktop.main_window   # tương đương
```

Nếu lệnh chạy xong mà **không hiện cửa sổ và cũng không báo lỗi**, gần như chắc chắn
PySide6 chưa cài đúng venv — kiểm tra `pip show PySide6-Essentials`.

Mở tab **Môi trường** để soát lại:

- ✅ xanh — sẵn sàng.
- ⚠ vàng — **tuỳ chọn**, không cần chuyển xanh. Thiếu thì bước đó chạy chế độ suy giảm
  (ví dụ thiếu Demucs thì bỏ qua tách nhạc nền; thiếu Rubber Band thì dùng atempo).
- ❌ đỏ — **bắt buộc**, phải sửa: FFmpeg, PyTorch, Faster-Whisper.

Nói cách khác: chỉ cần **hết dấu đỏ**, dấu vàng để nguyên vẫn dùng được app.

---

## Bước 5 — Build ra file chạy độc lập

```bash
pyinstaller packaging/subai_studio.spec --noconfirm
# -> dist/SubAIStudio/SubAIStudio.exe (Windows) hoặc dist/SubAIStudio/SubAIStudio (Linux)
```

File spec đã bao gồm sẵn mọi thứ chuỗi flag dài cần có — `--onedir --windowed
--name SubAIStudio`, `--collect-all` cho `torch`, `torchaudio`, `demucs`,
`faster_whisper`, `TTS`, `pyrubberband`, `soundfile`, `yt_dlp`, `pydantic`, và tự đóng
gói kèm `models_cache/` nếu thư mục đó tồn tại. Package nào chưa cài thì spec bỏ qua và
in ra danh sách, build vẫn chạy.

Vài lưu ý khi build:

- **Entry point là `run_desktop.py`**, không phải `desktop/main_window.py`. Cả hai đều mở
  được app, nhưng `run_desktop.py` khởi tạo `sys.path` sạch sẽ hơn cho môi trường đóng gói.
- **`--add-data` khác nhau theo OS**: Windows dùng `;`, Linux/macOS dùng `:`. Truyền
  `"models_cache;models_cache"` trên Linux sẽ hỏng. Spec xử lý sẵn nên không phải lo.
- **Nếu `models_cache/` không tồn tại**, truyền `--add-data` trỏ vào nó sẽ làm PyInstaller
  báo lỗi và dừng. Spec kiểm tra trước khi thêm.
- **`--collect-all torch` làm bản build phồng lên rất nhiều** (thường 8–15GB với đủ bộ AI)
  và mất khá lâu. Đây là cái giá để chắc chắn không dính `ModuleNotFoundError` lúc chạy
  `.exe`. Muốn gọn hơn thì bỏ `torch` khỏi `COLLECT_PACKAGES` trong spec rồi test kỹ lại.
- **Model AI không được nhúng sẵn**; lần chạy đầu app tự tải về `models_cache/`. Nên máy
  đích vẫn cần internet ở lần chạy đầu tiên.

Đã kiểm chứng: build bằng spec này trên Linux (chưa cài bộ AI) ra thư mục 174MB và binary
mở được cửa sổ bình thường.

Bản thương mại nhớ đặt `SUBAI_DEV_MODE=0` và nhúng `SUBAI_PUBLIC_KEY` — xem phần
**Đóng Gói & Bảo Mật** trong [README](../README.md).
