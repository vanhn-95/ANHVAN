# Kiến Trúc SubAI Studio

## 1. Sơ đồ tổng thể

```
┌────────────────────── Desktop (máy khách) ───────────────────────┐
│                                                                  │
│  desktop/main_window.py  ── QThread ──▶ desktop/worker.py        │
│         ▲  signals                          │                    │
│         │                                   ▼                    │
│  ProgressReporter  ◀──── callbacks ──── src/main_pipeline.py     │
│                                             │                    │
│   downloader → separator → ASR → translator → TTS → composer     │
└─────────────────────────────────┼────────────────────────────────┘
                                  │ HTTPS (chỉ text)
                          ┌───────▼────────┐
                          │ server/proxy   │  giữ GEMINI_API_KEY
                          │ FastAPI        │──▶ Gemini 2.5 Flash
                          └────────────────┘
```

## 2. Luồng dữ liệu một job

| Bước | Module | Vào | Ra |
|---|---|---|---|
| 1. Chuẩn bị video | `media_downloader.py` | URL hoặc file | `workspace/source.mp4` |
| 2. Tách âm thanh | `audio_separator.py` | video | `vocals.wav`, `no_vocals.wav` |
| 3. Trích phụ đề | `asr_engine.py` | `vocals.wav` | `List[Segment]` → `*.origin.srt` |
| 4. Dịch | `translator.py` | segments | segments có `translated` → `*.<lang>.srt` |
| 5. Lồng tiếng | `tts_engine.py` | segments + giọng mẫu | `dubbed_track.wav` |
| 6. Render | `video_composer.py` | video + audio | `*.dubbed.mp4` |

`Segment` (trong `src/utils.py`) là kiểu dữ liệu xuyên suốt: `start`, `end`, `text`,
`translated`. Mọi bước đều giữ nguyên số lượng và thứ tự segment, nên timeline không bao
giờ lệch.

## 3. Ba nguyên tắc thiết kế

### 3.1. Engine nạp lazy
Không module nào import `torch`, `demucs`, `faster_whisper` hay `TTS` ở cấp module. Chúng chỉ
được import bên trong hàm, ngay trước khi dùng. Mỗi engine có `available()` dựa trên
`importlib.util.find_spec`. Nhờ đó:

- App mở được trên máy chưa cài engine (hữu ích khi chỉ muốn xem/cấu hình).
- Tab **Môi trường** liệt kê chính xác thiếu gì kèm lệnh cài, thay vì crash khi khởi động.
- Test chạy được trong CI không GPU.

Thiếu Demucs thì bước tách nhạc nền chạy ở *chế độ suy giảm*: dùng thẳng audio gốc làm
vocal, ghi rõ cảnh báo vào log, các bước sau vẫn tiếp tục.

### 3.2. UI không bao giờ đơ
`PipelineWorker(QThread)` chạy pipeline ở thread nền. Pipeline chỉ biết tới interface
`ProgressReporter`; worker cắm callback của nó vào Qt signals (`log`, `stage_changed`,
`progress_changed`). Signal được Qt xếp hàng về UI thread nên không có race condition trên
widget.

Huỷ job: `reporter.cancel()` bật một `threading.Event`; các vòng lặp dài gọi
`check_cancelled()` và ném `CancelledError` ở điểm an toàn gần nhất.

Tiến độ: mỗi bước có trọng số (`plan_stages`), reporter quy đổi `progress(0..1)` trong bước
hiện tại thành phần trăm tổng thể — thanh progress không bao giờ nhảy giật lùi.

### 3.3. API key không nằm ở client
Client gửi cho proxy đúng ba thứ: danh sách câu thoại, cặp mã ngôn ngữ, license key. Proxy
dựng prompt, gọi Gemini, và parse lại output dạng `n|text` để **bảo đảm số dòng trả về đúng
bằng số dòng gửi đi**. Dòng nào model bỏ sót thì giữ nguyên bản gốc thay vì đẩy lệch cả file
phụ đề.

## 4. Căn khớp thời lượng khi lồng tiếng

Câu dịch thường dài/ngắn hơn câu gốc. `tts_engine.py` xử lý theo thứ tự:

1. Tổng hợp câu bằng XTTS-v2 (kèm `speaker_wav` nếu bật voice cloning).
2. Đo độ dài thực tế, tính `ratio = actual / target`.
3. `ratio ≤ 1.02`: giữ nguyên, phần dư sẽ là khoảng lặng.
4. `ratio > 1.02`: tăng tốc bằng `pyrubberband` (giữ cao độ), giới hạn bởi
   `max_speed_ratio` (mặc định 1.35) để giọng không bị méo. Không có rubberband thì rơi về
   `atempo` của FFmpeg.
5. Ghép các clip vào đúng offset bằng `adelay` + `amix`, chia lô 32 clip mỗi filter graph để
   không vượt giới hạn dòng lệnh khi video có hàng trăm câu thoại.

Giọng mẫu: nếu người dùng không chọn file, hệ thống tự cắt 3 câu dài nhất (2–12 giây) từ
track vocal đã tách và nối lại làm reference.

## 5. Auto-ducking

`video_composer.mix_audio` dùng `sidechaincompress`: track lồng tiếng vừa là tín hiệu chính
vừa là sidechain điều khiển nén nhạc nền. `attack=20ms` để nhạc hạ kịp khi bắt đầu câu,
`release=400ms` để nhạc trở lại mượt sau câu. `alimiter` chặn clipping ở khâu cuối.

## 6. Bản quyền

- `get_hwid()`: SHA-256 của (kiến trúc + OS + serial mainboard/CPU trên Windows,
  `IOPlatformUUID` trên macOS, `/etc/machine-id` trên Linux), fallback về MAC address.
- License = `base64(payload).base64(chữ ký RSA-PSS)`, payload JSON gồm `hwid`, `customer`,
  `expires`. `hwid = "*"` là license dùng chung nhiều máy.
- Client chỉ có **public key** nên không thể tự phát hành. Private key nằm ở
  `tools/license_tool.py` phía nhà phát hành.
- `SUBAI_DEV_MODE=1` (mặc định khi chạy từ mã nguồn) bỏ qua kiểm tra; bản build thương mại
  phải đặt `SUBAI_DEV_MODE=0`.

## 7. Cấu hình

`JobConfig` (dataclass) là nguồn sự thật duy nhất cho một job — UI, CLI và test đều dùng
chung, và `validate()` trả về thông báo lỗi tiếng Việt hiển thị thẳng cho người dùng.
`AppSettings` lưu job gần nhất + danh sách nguồn gần đây vào `~/.subai/settings.json`.

`src/env_file.py` là loader `.env` viết tay (không cần `python-dotenv`). Nó được gọi ngay
trong `src/__init__.py` và `server/__init__.py`, tức là **trước** khi `config.py` và
`security_guard.py` đọc `os.environ` ở cấp module — nếu nạp muộn hơn thì các giá trị mặc
định đã bị "đóng băng" mất rồi. Biến môi trường có sẵn trong shell luôn thắng file `.env`,
nên `GEMINI_API_KEY=xxx uvicorn ...` vẫn đè được lên file khi cần.

## 8. Đa nhà cung cấp AI (Factory Pattern)

`src/providers.py` là nơi duy nhất biết về từng hãng AI:

```
TranslatorAgent (ABC)
├── complete(prompt)          ← mỗi hãng tự cài đặt
├── translate_lines(...)      ← dùng chung: dựng prompt, đếm dòng, vá dòng thiếu
├── verify()                  ← dùng chung: gọi thử, trả (mã, mô tả)
└── create(provider, key, model)   ← FACTORY

OpenAIAgent      → https://api.openai.com/v1/chat/completions
└── DeepSeekAgent → https://api.deepseek.com/v1  (kế thừa: cùng giao thức)
GeminiAgent      → https://generativelanguage.googleapis.com/v1beta
```

Ba quyết định đáng chú ý:

**Gọi REST trực tiếp, không dùng SDK từng hãng.** Thêm provider mới không kéo theo
dependency mới, không dính xung đột phiên bản giữa các SDK, và bản PyInstaller không phình
thêm. Đổi lại phải tự dựng payload — chi phí nhỏ vì cả ba đều là JSON phẳng.

**DeepSeek kế thừa `OpenAIAgent`**, chỉ đổi `base_url`. DeepSeek cố tình làm API tương
thích OpenAI nên viết lại là thừa.

**Phân loại lỗi dùng chung** (`classify_http_error`): 401/403 → `bad_key`, 429/402 →
`quota`, 404 → `bad_model`, 5xx → `provider_down`, lỗi socket → `network`. Body được soi
thêm vì có hãng trả 400 kèm `API_KEY_INVALID` thay vì 401. Nhờ vậy giao diện chỉ cần xử lý
một tập mã lỗi, không cần biết đang nói chuyện với hãng nào.

Provider/key/model đi từ `config.ini` → biến môi trường của tiến trình con
(`SUBAI_PROVIDER`, `SUBAI_API_KEY`, `SUBAI_MODEL`) → server đọc lại **ở mỗi lần gọi**. Vì
vậy đổi nhà cung cấp chỉ cần restart tiến trình server, không phải sửa code.
