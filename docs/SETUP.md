# Hướng Dẫn Cài Đặt & Build SubAI Studio

## ⚡ Cách nhanh nhất — không cần gõ lệnh

**Windows**: nhấp đôi vào **`start_windows.bat`**.
**Linux/macOS**: chạy `./start_unix.sh`.

Script tự tìm Python, tự tạo venv, tự cài thư viện, rồi mở app. Lần đầu mất vài phút
(tải ~150MB). Có lỗi thì nó dừng lại và in ra lệnh cần chạy — cửa sổ **không tự tắt**.

**Đang lỗi mà không rõ vì sao?** Chạy công cụ chẩn đoán:

```bash
python check_setup.py
```

Nó in ra đúng cái gì thiếu và lệnh phải gõ. Xem thêm mục
[Lỗi thường gặp](#-lỗi-thường-gặp) ở cuối trang.

---

> **Phiên bản Python: 3.11** — đây là bản duy nhất được dùng để phát triển và kiểm thử
> dự án này. Coqui `TTS` chưa hỗ trợ Python 3.12+ nên cài trên 3.12 sẽ hỏng bước lồng
> tiếng. Kiểm tra trước khi tạo venv:
>
> ```bash
> python --version      # phải ra Python 3.11.x
> ```
>
> Máy có nhiều bản Python thì chỉ đích danh: `py -3.11 -m venv venv` (Windows) hoặc
> `python3.11 -m venv venv` (Linux/macOS).

---

## Bước 1 — Môi trường ảo & dependencies

Không cài bằng `root` hay Python toàn cục: PyInstaller sẽ gom nhầm thư viện hệ thống
vào bản build.

```bash
# Windows:
py -3.11 -m venv venv
venv\Scripts\activate
# Linux / macOS:
python3.11 -m venv venv
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

---

## 🔧 Lỗi thường gặp

Trước hết cứ chạy `python check_setup.py` — phần lớn trường hợp nó chỉ thẳng ra nguyên nhân.

### Nhấp đôi `run_desktop.py` thì cửa sổ đen nháy lên rồi tắt ngay

Đây **không phải** app bị lỗi im lặng: Python chạy, gặp lỗi, in ra rồi đóng cửa sổ trước
khi bạn kịp đọc. Dùng **`start_windows.bat`** thay vì nhấp đôi file `.py` — nó giữ cửa sổ
lại để bạn đọc thông báo.

### Giải nén ra thư mục lồng nhau `SubAIStudio\SubAIStudio`

File zip có sẵn thư mục gốc `SubAIStudio/`, nên nếu bạn tạo thêm một thư mục tên
`SubAIStudio` rồi giải nén vào đó thì sẽ thành hai tầng. Mọi lệnh phải chạy ở **tầng trong**
— tầng nào chứa `run_desktop.py` thì đó là tầng đúng. Kiểm tra bằng `dir` (Windows) hoặc
`ls`: phải thấy `run_desktop.py`, `desktop`, `src`.

### `'python' is not recognized as an internal or external command`

Python chưa có trong PATH. Cài lại Python 3.11 và **tick ô "Add python.exe to PATH"**, hoặc
dùng `py -3.11` thay cho `python`. Cài xong phải **mở lại** cửa sổ terminal.

### Gõ `python` thì Microsoft Store hiện lên

Đó là bản Python giả lập của Windows. Tải bản thật tại
<https://www.python.org/downloads/release/python-3119/>, hoặc dùng `py -3.11`.

### `ModuleNotFoundError: No module named 'PySide6'`

Chưa cài thư viện, hoặc đã cài nhưng **chưa kích hoạt venv**. Dấu hiệu đã kích hoạt: đầu
dòng lệnh có chữ `(venv)`.

```powershell
venv\Scripts\activate
pip install -r requirements-desktop.txt
```

### `ModuleNotFoundError: No module named 'src'` hoặc `'desktop'`

Đang chạy sai thư mục. `cd` vào thư mục chứa `run_desktop.py` rồi chạy lại.

### App mở được nhưng tab Môi trường toàn dấu đỏ

Bình thường nếu mới cài `requirements-desktop.txt` — bộ đó chỉ đủ mở giao diện. Muốn xử lý
video thật thì cài tiếp `requirements.txt` và FFmpeg (xem Bước 1 và Bước 2).

### Bấm "Bắt đầu xử lý" thì báo không kết nối được Proxy Server

Proxy chưa chạy. Mở thêm một cửa sổ terminal nữa:

```bash
uvicorn server.proxy_server:app --host 0.0.0.0 --port 8000
```

Muốn bỏ qua bước dịch để test cho nhanh thì bỏ tick **"Dịch phụ đề bằng AI"** — app sẽ chỉ
trích xuất phụ đề gốc.

### Vẫn không được

Chụp lại **toàn bộ chữ** mà `python check_setup.py` in ra (hoặc thông báo lỗi đầy đủ trong
terminal) — đó là thứ cần thiết để tìm ra nguyên nhân. Ảnh chụp thư mục không cho biết app
lỗi ở đâu.
