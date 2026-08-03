---
title: Chuyển đổi Giọng nói
emoji: 🎙️
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
short_description: Bóc băng cuộc gọi tiếng Việt thành hội thoại dạng chat
---

# Chuyển đổi Giọng nói

Ứng dụng web Speech-to-Text phân tích cuộc gọi, hiển thị kết quả dưới dạng **khung chat đối thoại** với tự động tách hai người nói (speaker diarization).

- **Khách hàng** → bong bóng bên **trái**, nền trắng/xám nhạt
- **Thẩm định viên** → bong bóng bên **phải**, nền gradient xanh dương/tím, chữ trắng
- Mỗi lượt thoại kèm timestamp (`00:00`), có nút **Sao chép nội dung** và nút **← Phân tích cuộc gọi khác**

---

## Triển khai lên Hugging Face Spaces

### 1. Tạo Space

Vào https://huggingface.co/new-space và chọn:

| Mục | Giá trị |
|---|---|
| Space SDK | **Gradio** |
| Hardware | **CPU basic** là đủ (toàn bộ nhận dạng chạy trên API bên ngoài) |
| Visibility | Private nếu chưa muốn công khai |

### 2. Đẩy mã nguồn lên

```bash
git remote add space https://huggingface.co/spaces/<tên-tài-khoản>/<tên-space>
git push space HEAD:main
```

### 3. Khai báo Secrets

Vào **Settings → Variables and secrets** của Space, thêm dưới dạng **Secret** (không phải Variable):

| Tên | Bắt buộc | Ý nghĩa |
|---|---|---|
| `DEEPGRAM_API_KEY` | Cần ít nhất 1 | Key Deepgram — https://console.deepgram.com/ |
| `GROQ_API_KEY` | trong 2 key | Key Groq — https://console.groq.com/keys |
| `APP_USERNAME` | Nên có | Tên đăng nhập để giới hạn truy cập |
| `APP_PASSWORD` | Nên có | Mật khẩu đăng nhập |

App tự phát hiện key nào đã khai báo và chỉ hiện engine tương ứng. Space sẽ tự khởi động lại sau khi lưu secret.

> **Quan trọng về chi phí:** Space công khai mà không đặt `APP_USERNAME`/`APP_PASSWORD` thì **bất kỳ ai trên Internet cũng dùng được API key của bạn** và bạn trả tiền cho toàn bộ lượt dùng đó. Hãy đặt mật khẩu, hoặc để Space ở chế độ Private. App ghi cảnh báo vào log nếu phát hiện đang chạy trên Space mà không có mật khẩu.

### 4. Biến tuỳ chọn

Khai báo dưới dạng **Variable** (không nhạy cảm):

| Tên | Mặc định | Ý nghĩa |
|---|---|---|
| `CONCURRENCY_LIMIT` | `8` | Số cuộc gọi xử lý song song |
| `QUEUE_MAX_SIZE` | `40` | Số người tối đa được xếp hàng chờ |
| `MAX_FILE_MB` | `100` | Giới hạn dung lượng file tải lên |
| `MAX_RETRIES` | `3` | Số lần thử lại khi API lỗi tạm thời |
| `READ_TIMEOUT` | `300` | Thời gian chờ tối đa API trả kết quả (giây) |
| `DELETE_UPLOAD_AFTER` | `1` | Xoá file ghi âm khỏi máy chủ sau khi bóc băng. Đặt `0` để giữ lại |
| `DEEPGRAM_MODEL` | `nova-2` | Model Deepgram |
| `GROQ_MODEL` | `whisper-large-v3-turbo` | Model Groq |
| `LOG_LEVEL` | `INFO` | Mức ghi log |

---

## Chạy trên máy cá nhân

```bash
cp .env.example .env     # điền DEEPGRAM_API_KEY hoặc GROQ_API_KEY
./run.sh                 # 1 lệnh: tạo venv + cài thư viện + mở http://localhost:7860
```

<details>
<summary>Chạy thủ công</summary>

```bash
pip install -r requirements.txt && python app.py
```
</details>

---

## Vận hành nhiều người dùng

| Hạng mục | Cách xử lý |
|---|---|
| **Xếp hàng** | Gradio queue, mặc định 8 luồng song song, tối đa 40 người chờ. Công việc chỉ là chờ mạng nên thread rất rẻ — có thể nâng `CONCURRENCY_LIMIT` nếu hạn mức API cho phép. |
| **Tách phiên** | Mỗi người dùng có phiên riêng, không thấy kết quả của nhau. Không có biến toàn cục lưu dữ liệu người dùng. |
| **Lỗi tạm thời** | Tự thử lại tối đa 3 lần với backoff 1s → 2s → 4s khi gặp HTTP 429/5xx hoặc lỗi mạng. |
| **Quá tải API** | Khi nhà cung cấp trả 429, người dùng nhận thông báo tiếng Việt rõ ràng thay vì lỗi kỹ thuật. |
| **Riêng tư** | File ghi âm bị xoá khỏi máy chủ ngay khi bóc băng xong. Gradio cũng tự dọn cache mỗi 30 phút. |
| **Rò rỉ thông tin** | Nội dung lỗi thô từ nhà cung cấp chỉ ghi vào log của máy chủ, không hiện ra giao diện. |
| **Bảo vệ tài nguyên** | Chặn file quá `MAX_FILE_MB`, chặn sớm file vượt giới hạn 25MB của Groq. |

Chi phí do bạn trả cho Deepgram/Groq theo số phút audio, không phụ thuộc HF Spaces.

---

## Về tốc độ (< 15 giây cho file 15 phút)

Toàn bộ phần nhận dạng chạy trên hạ tầng inference của nhà cung cấp, không xử lý cục bộ:

| Engine | Model | Diarization | Ghi chú |
|---|---|---|---|
| **Deepgram** | `nova-2` | Gốc, chính xác | Mặc định. File 15 phút thường trả về trong khoảng 5–10 giây. |
| **Groq** | `whisper-large-v3-turbo` | Suy đoán theo khoảng lặng | Nhanh nhất, nhưng Whisper **không** hỗ trợ diarization gốc — việc tách vai chỉ mang tính tương đối. Giới hạn file 25MB. |

Thời gian thực tế còn phụ thuộc băng thông upload (file 15 phút mp3 ≈ 14MB). Thời gian xử lý thật và thời lượng audio được hiển thị ngay dưới khung kết quả sau mỗi lần chạy.

---

## Tuỳ chọn trong app

- **Engine nhận dạng** — chỉ hiện những engine đã có API key.
- **Ngôn ngữ** — `vi` (mặc định), `en`, `multi`.
- **Đảo vai hai người nói** — mặc định Speaker 0 = Khách hàng, Speaker 1 = Thẩm định viên. Nếu cuộc gọi do thẩm định viên mở lời trước và bị gán nhầm vai, bật tuỳ chọn này rồi phân tích lại.

## Định dạng hỗ trợ

`.mp3` · `.wav` · `.m4a` · `.mp4` · `.aac` · `.ogg` · `.flac` · `.webm`

## Cấu trúc

```
app.py            # Toàn bộ ứng dụng: STT client, dựng chat timeline, custom CSS
requirements.txt  # Thư viện đã ghim phiên bản
README.md         # Tài liệu + cấu hình Hugging Face Space (phần YAML đầu file)
.env.example      # Mẫu cấu hình khi chạy máy cá nhân
run.sh            # Cài đặt + chạy bằng 1 lệnh
```
