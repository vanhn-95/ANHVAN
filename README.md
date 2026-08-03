# Chuyển đổi Giọng nói

Ứng dụng web Speech-to-Text phân tích cuộc gọi, hiển thị kết quả dưới dạng **khung chat đối thoại** với tự động tách hai người nói (speaker diarization).

- **Khách hàng** → bong bóng bên **trái**, nền trắng/xám nhạt
- **Thẩm định viên** → bong bóng bên **phải**, nền gradient xanh dương/tím, chữ trắng
- Mỗi lượt thoại kèm timestamp (`00:00`), có nút **Sao chép nội dung** và nút **← Phân tích cuộc gọi khác** để reset

---

## Chạy ứng dụng

### 1. Điền API Key

```bash
cp .env.example .env
```

Mở file `.env` và điền **ít nhất một** key:

```env
DEEPGRAM_API_KEY=your_deepgram_key_here
GROQ_API_KEY=your_groq_key_here
```

| Nguồn key | Đường dẫn |
|---|---|
| Deepgram (khuyến nghị) | https://console.deepgram.com/ |
| Groq | https://console.groq.com/keys |

### 2. Chạy — 1 lệnh duy nhất

```bash
./run.sh
```

Lệnh này tự tạo virtualenv, cài thư viện và mở app tại **http://localhost:7860**.

<details>
<summary>Nếu muốn chạy thủ công</summary>

```bash
pip install -r requirements.txt && python app.py
```
</details>

---

## Về tốc độ (< 15 giây cho file 15 phút)

Toàn bộ phần nhận dạng chạy trên hạ tầng inference của nhà cung cấp, không xử lý cục bộ:

| Engine | Model | Diarization | Ghi chú |
|---|---|---|---|
| **Deepgram** | `nova-2` | Gốc, chính xác | Mặc định. Xử lý audio nhanh hơn realtime rất nhiều; file 15 phút thường trả về trong khoảng 5–10 giây. |
| **Groq** | `whisper-large-v3-turbo` | Suy đoán theo khoảng lặng | Nhanh nhất, nhưng Whisper **không** hỗ trợ diarization gốc — việc tách vai chỉ mang tính tương đối. Giới hạn file ~25MB. |

Thời gian thực tế còn phụ thuộc băng thông upload của bạn (file 15 phút mp3 ≈ 14MB). Thời gian xử lý thật được hiển thị ngay dưới khung kết quả sau mỗi lần chạy.

---

## Tuỳ chọn nâng cao (trong app)

- **Engine nhận dạng** — chọn Deepgram hoặc Groq.
- **Ngôn ngữ** — `vi` (mặc định), `en`, `multi`.
- **Đảo vai hai người nói** — mặc định Speaker 0 = Khách hàng, Speaker 1 = Thẩm định viên. Nếu cuộc gọi do thẩm định viên mở lời trước và bị gán nhầm vai, bật tuỳ chọn này rồi phân tích lại.

## Định dạng hỗ trợ

`.mp3` · `.wav` · `.m4a` · `.mp4` · `.aac` · `.ogg` · `.flac` · `.webm`

## Cấu trúc

```
app.py            # Toàn bộ ứng dụng: STT client, dựng chat timeline, custom CSS
requirements.txt  # Thư viện
.env.example      # Mẫu cấu hình API key
run.sh            # Cài đặt + chạy bằng 1 lệnh
```
