import os
import json
import requests
import hashlib
import hmac
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import pytz
from redis import Redis

# --- CẤU HÌNH ---
TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')
CHINA_TIMEZONE = pytz.timezone('Asia/Shanghai')
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRON_SECRET = os.getenv("CRON_SECRET")
REMINDER_THRESHOLD_MINUTES = 5

# --- KẾT NỐI CƠ SỞ DỮ LIỆU ---
try:
    kv_url = os.getenv("teeboov2_REDIS_URL")
    if not kv_url: raise ValueError("teeboov2_REDIS_URL is not set.")
    kv = Redis.from_url(kv_url, decode_responses=True)
except Exception as e:
    print(f"FATAL: Could not connect to Redis. Error: {e}"); kv = None
# --- LOGIC QUẢN LÝ CÔNG VIỆC ---
def _get_processed_airdrop_events():
    """
    Hàm nội bộ: Lấy và xử lý dữ liệu airdrop, trả về danh sách các sự kiện
    đã được lọc với thời gian hiệu lực đã được tính toán.
    Đây là hàm logic cốt lõi.
    """
    AIRDROP_API_URL = "https://alpha123.uk/api/data?fresh=1"
    PRICE_API_URL = "https://alpha123.uk/api/price/?batch=today"
    HEADERS = {
      'referer': 'https://alpha123.uk/index.html',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    def _get_price_data():
        try:
            res = requests.get(PRICE_API_URL, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                price_json = res.json()
                if price_json.get('success') and 'prices' in price_json:
                    return price_json['prices']
        except Exception: pass
        return {}

    def _filter_and_deduplicate_events(events):
        processed = {}
        for event in events:
            key = (event.get('date'), event.get('token'))
            if key not in processed or event.get('phase', 1) > processed[key].get('phase', 1):
                processed[key] = event
        return list(processed.values())

    # --- SỬA LỖI XỬ LÝ THỜI GIAN KHÔNG HỢP LỆ TẠI ĐÂY ---
    def _get_effective_event_time(event):
        """
        Trả về thời gian hiệu lực của sự kiện dưới dạng datetime object (đã ở múi giờ Việt Nam).
        Xử lý an toàn các trường hợp time không hợp lệ như 'delay'.
        """
        event_date_str = event.get('date')
        event_time_str = event.get('time')
        
        # Bước 1: Kiểm tra đầu vào cơ bản. Nếu không có date, time, hoặc không có dấu ':' thì bỏ qua.
        if not (event_date_str and event_time_str and ':' in event_time_str):
            return None
            
        try:
            # Bước 2: Làm sạch chuỗi thời gian. Lấy phần đầu tiên trước khoảng trắng.
            # Điều này sẽ chuyển "13:00 Delay" thành "13:00".
            cleaned_time_str = event_time_str.strip().split()[0]
            
            # Bước 3: Phân tích thời gian đã được làm sạch
            naive_dt = datetime.strptime(f"{event_date_str} {cleaned_time_str}", '%Y-%m-%d %H:%M')
            
            if event.get('phase') == 2:
                naive_dt += timedelta(hours=18)
            
            china_dt = CHINA_TIMEZONE.localize(naive_dt)
            vietnam_dt = china_dt.astimezone(TIMEZONE)
            
            return vietnam_dt
        except Exception:
            # Bước 4: Nếu có bất kỳ lỗi nào xảy ra (ValueError, pytz error...),
            # trả về None để xử lý như một sự kiện không có thời gian cụ thể.
            return None

    try:
        airdrop_res = requests.get(AIRDROP_API_URL, headers=HEADERS, timeout=20)
        if airdrop_res.status_code != 200: return None, f"❌ Lỗi khi gọi API sự kiện (Code: {airdrop_res.status_code})."
        
        data = airdrop_res.json()
        airdrops = data.get('airdrops', [])
        if not airdrops: return [], None

        price_data = _get_price_data()
        definitive_events = _filter_and_deduplicate_events(airdrops)
        
        for event in definitive_events:
            event['effective_dt'] = _get_effective_event_time(event)
            event['price_data'] = price_data

        return definitive_events, None
    except requests.RequestException: return None, "❌ Lỗi mạng khi lấy dữ liệu sự kiện."
    except json.JSONDecodeError: return None, "❌ Dữ liệu trả về từ API sự kiện không hợp lệ."

def _get_processed_airdrop_events():
    """
    Hàm nội bộ: Lấy và xử lý dữ liệu airdrop, trả về danh sách các sự kiện
    đã được lọc với thời gian hiệu lực đã được tính toán.
    Đây là hàm logic cốt lõi.
    """
    AIRDROP_API_URL = "https://alpha123.uk/api/data?fresh=1"
    PRICE_API_URL = "https://alpha123.uk/api/price/?batch=today"
    HEADERS = {
      'referer': 'https://alpha123.uk/index.html',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    def _get_price_data():
        try:
            res = requests.get(PRICE_API_URL, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                price_json = res.json()
                if price_json.get('success') and 'prices' in price_json:
                    return price_json['prices']
        except Exception: pass
        return {}

    # SỬA LỖI: Hàm _filter_and_deduplicate_events đã bị XÓA BỎ.

    def _get_effective_event_time(event):
        """
        Trả về thời gian hiệu lực của sự kiện dưới dạng datetime object (đã ở múi giờ Việt Nam).
        """
        event_date_str = event.get('date')
        event_time_str = event.get('time')
        if not (event_date_str and event_time_str and ':' in event_time_str):
            return None
        try:
            cleaned_time_str = event_time_str.strip().split()[0]
            naive_dt = datetime.strptime(f"{event_date_str} {cleaned_time_str}", '%Y-%m-%d %H:%M')
            if event.get('phase') == 2:
                naive_dt += timedelta(hours=18)
            china_dt = CHINA_TIMEZONE.localize(naive_dt)
            vietnam_dt = china_dt.astimezone(TIMEZONE)
            return vietnam_dt
        except Exception:
            return None

    try:
        airdrop_res = requests.get(AIRDROP_API_URL, headers=HEADERS, timeout=20)
        if airdrop_res.status_code != 200: return None, f"❌ Lỗi khi gọi API sự kiện (Code: {airdrop_res.status_code})."
        
        data = airdrop_res.json()
        airdrops = data.get('airdrops', [])
        if not airdrops: return [], None

        price_data = _get_price_data()
        
        # SỬA LỖI: Không còn gom nhóm. Xử lý trực tiếp danh sách 'airdrops'
        for event in airdrops:
            event['effective_dt'] = _get_effective_event_time(event)
            event['price_data'] = price_data

        return airdrops, None
    except requests.RequestException: return None, "❌ Lỗi mạng khi lấy dữ liệu sự kiện."
    except json.JSONDecodeError: return None, "❌ Dữ liệu trả về từ API sự kiện không hợp lệ."

def get_airdrop_events() -> str:
    """
    Hàm giao diện: Gọi hàm logic cốt lõi và định dạng kết quả thành tin nhắn cho người dùng.
    Hiển thị thêm ngày cho các sự kiện Upcoming.
    """
    processed_events, error_message = _get_processed_airdrop_events()
    if error_message:
        return error_message
    if not processed_events:
        return "ℹ️ Không tìm thấy sự kiện airdrop nào."

    def _format_event_message(event, price_data, effective_dt, include_date=False):
        token, name = event.get('token', 'N/A'), event.get('name', 'N/A')
        points, amount_str = event.get('points') or '-', event.get('amount') or '-'
        
        display_time = event.get('time') or 'TBA'
        # Xử lý đặc biệt cho các chuỗi không phải thời gian
        is_special_time = "Tomorrow" in display_time or "Day after" in display_time
        
        if effective_dt and not is_special_time:
            time_part = effective_dt.strftime('%H:%M')
            if include_date:
                date_part = effective_dt.strftime('%d/%m')
                display_time = f"{time_part} {date_part}"
            else:
                display_time = time_part
        
        price_str, value_str = "", ""
        if token in price_data:
            price_value = price_data[token].get('dex_price') or price_data[token].get('price', 0)
            if price_value > 0:
                price_str = f" (`${price_value:,.4f}`)"
                try:
                    value = float(amount_str) * price_value
                    value_str = f"\n  Value: `${value:,.2f}`"
                except (ValueError, TypeError): pass
        
        time_str = f"`{display_time}`"
        return (f"*{token} - {name}*{price_str}\n"
                f"  Points: `{points}` | Amount: `{amount_str}`{value_str}\n"
                f"  Time: {time_str}")

    now_vietnam = datetime.now(TIMEZONE)
    today_date = now_vietnam.date()
    todays_events, upcoming_events = [], []

    for event in processed_events:
        effective_dt = event['effective_dt']
        if effective_dt and effective_dt < now_vietnam: continue
        
        event_date_str = event.get('date')
        if not event_date_str: continue

        try:
            event_day = effective_dt.date() if effective_dt else datetime.strptime(event_date_str, '%Y-%m-%d').date()
        except ValueError:
            continue

        if event_day == today_date:
            todays_events.append(event)
        elif event_day > today_date:
            upcoming_events.append(event)

    todays_events.sort(key=lambda x: x.get('effective_dt') or datetime.max.replace(tzinfo=TIMEZONE))
    upcoming_events.sort(key=lambda x: x.get('effective_dt') or datetime.max.replace(tzinfo=TIMEZONE))
    
    message_parts = []
    price_data = processed_events[0]['price_data'] if processed_events else {}
    
    if todays_events:
        today_messages = [_format_event_message(e, price_data, e['effective_dt']) for e in todays_events]
        message_parts.append("🎁 *Today's Airdrops:*\n\n" + "\n\n".join(today_messages))

    if upcoming_events:
        if message_parts: message_parts.append("\n\n" + "-"*25 + "\n\n")
        
        upcoming_messages = []
        for event in upcoming_events:
            effective_dt = event['effective_dt']
            # Gọi hàm format cho Upcoming events, với include_date=True
            upcoming_messages.append(_format_event_message(event, price_data, effective_dt, include_date=True))
            
        message_parts.append("🗓️ *Upcoming Airdrops:*\n\n" + "\n\n".join(upcoming_messages))

    if not message_parts:
        return "ℹ️ Không có sự kiện airdrop nào đáng chú ý trong hôm nay và các ngày sắp tới."
    
    return "".join(message_parts)

def parse_task_from_string(task_string: str) -> tuple[datetime | None, str | None]:
    try:
        time_part, name_part = task_string.split(' - ', 1)
        name_part = name_part.strip()
        if not name_part: return None, None
        now = datetime.now(TIMEZONE)
        dt_naive = datetime.strptime(time_part.strip(), '%d/%m %H:%M')
        return now.replace(month=dt_naive.month, day=dt_naive.day, hour=dt_naive.hour, minute=dt_naive.minute, second=0, microsecond=0), name_part
    except ValueError: return None, None

def send_telegram_message(chat_id, text, **kwargs) -> int | None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', **kwargs}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200 and response.json().get('ok'): return response.json().get('result', {}).get('message_id')
        print(f"Error sending message, response: {response.text}"); return None
    except requests.RequestException as e: print(f"Error sending message: {e}"); return None
def pin_telegram_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage"
    payload = {'chat_id': chat_id, 'message_id': message_id, 'disable_notification': False}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200: print(f"Error pinning message: {response.text}")
    except requests.RequestException as e: print(f"Error pinning message: {e}")
def edit_telegram_message(chat_id, msg_id, text, **kwargs):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'Markdown', **kwargs}
    try: requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e: print(f"Error editing message: {e}")
def answer_callback_query(cb_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try: requests.post(url, json={'callback_query_id': cb_id}, timeout=5)
    except requests.RequestException as e: print(f"Error answering callback: {e}")
def delete_telegram_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    payload = {'chat_id': chat_id, 'message_id': message_id}
    try: requests.post(url, json=payload, timeout=5)
    except requests.RequestException as e: print(f"Error deleting message: {e}")
# --- WEB SERVER (FLASK) ---
app = Flask(__name__)
@app.route('/', methods=['POST'])
def webhook():
    if not BOT_TOKEN: return "Server configuration error", 500
    data = request.get_json()
    if "callback_query" in data:
        cb = data["callback_query"]; answer_callback_query(cb["id"])
        
        # Logic xử lý refresh portfolio cũ
        if cb.get("data") == "refresh_portfolio" and "reply_to_message" in cb["message"]:
            result = process_portfolio_text(cb["message"]["reply_to_message"]["text"])
            if result: edit_telegram_message(cb["message"]["chat"]["id"], cb["message"]["message_id"], text=result, reply_markup=cb["message"]["reply_markup"])
        
        # --- THÊM LOGIC MỚI ĐỂ XỬ LÝ REFRESH SỰ KIỆN ---
        elif cb.get("data") == "refresh_events":
            # 1. Hiển thị thông báo nhỏ "Đang tải..." cho người dùng
            # (answer_callback_query đã được gọi ở trên)
            
            # 2. Lấy lại danh sách sự kiện mới nhất
            new_text = get_airdrop_events()
            
            # 3. Lấy nội dung tin nhắn cũ để so sánh
            old_text = cb["message"]["text"]
            
            # 4. Chỉ cập nhật nếu nội dung có thay đổi (tối ưu hóa)
            if new_text != old_text:
                edit_telegram_message(
                    chat_id=cb["message"]["chat"]["id"],
                    msg_id=cb["message"]["message_id"],
                    text=new_text,
                    # Gửi lại cấu trúc nút bấm để nó không bị biến mất
                    reply_markup=json.dumps(cb["message"]["reply_markup"])
                )
                
        return jsonify(success=True)
    if "message" not in data or "text" not in data["message"]: return jsonify(success=True)
    chat_id = data["message"]["chat"]["id"]; msg_id = data["message"]["message_id"]
    text = data["message"]["text"].strip(); parts = text.split(); cmd = parts[0].lower()
    if cmd.startswith('/'):
        if cmd == "/start":
            start_message = ("Gòi, cần gì fen?\n\n"
                             "**Chức năng Lịch hẹn:**\n"
                             "`/add DD/MM HH:mm - Tên`\n"
                             "`/list`, `/del <số>`, `/edit <số> ...`\n\n"
                             "**Chức năng Crypto:**\n"
                             "`/alpha time - tên event - amount contract`\n"
                             "**Ví dụ: /alpha 20/08 22:00 - Alpha: GAME - 132 0x825459139c897d769339f295e962396c4f9e4a4d**\n"
                             "`/gia <ký hiệu>`\n"
                             "`/calc <ký hiệu> <số lượng>`\n"
                             "`/gt <thuật ngữ>`\n"
                             "`/tr <nội dung>`\n"
                             "`/event` - Xem lịch airdrop sắp tới\n"
                             "`/autonotify on` - Bật thông báo tự động cho nhóm\n"
                             "`/perp <ký hiệu>`\n"
                             "`/alert <contract> <%>`\n"
                             "`/unalert <contract>`\n"
                             "`/alerts`\n\n"
                             "1️⃣ *Tra cứu Token theo Contract*\n"
                             "2️⃣ *Tính Portfolio (Event trade Alpha)*\n"
                             "Cú pháp: <số lượng> <contract> <chain>\n"
                             "Ví dụ: 20000 0x825459139c897d769339f295e962396c4f9e4a4d bsc"
                             "2️⃣ *Tính Portfolio (Giá Binance Futures)*\n" # Thêm hướng dẫn
                             "Gõ `/folio` và xuống dòng nhập danh sách:\n"
                             "`<số lượng> <ký hiệu>`\n"
                             "_Ví dụ:_\n"
                             "```\n/folio\n0.5 btc\n10 eth\n```")
            send_telegram_message(chat_id, text=start_message)
                # Sửa dòng này để bao gồm /del
        elif cmd == "/autonotify":
            if len(parts) < 2:
                send_telegram_message(chat_id, text="Cú pháp sai. Dùng: `/autonotify on` hoặc `/autonotify off`.", reply_to_message_id=msg_id)
            else:
                sub_command = parts[1].lower()
                if sub_command == 'on':
                    if kv:
                        kv.sadd("event_notification_groups", chat_id)
                        send_telegram_message(chat_id, text="✅ Đã bật tính năng tự động thông báo và ghim tin nhắn cho các sự kiện airdrop trong nhóm này.")
                    else:
                        send_telegram_message(chat_id, text="❌ Lỗi: Không thể thực hiện do không kết nối được DB.")
                elif sub_command == 'off':
                    if kv:
                        kv.srem("event_notification_groups", chat_id)
                        send_telegram_message(chat_id, text="✅ Đã tắt tính năng tự động thông báo sự kiện trong nhóm này.")
                    else:
                        send_telegram_message(chat_id, text="❌ Lỗi: Không thể thực hiện do không kết nối được DB.")
                else:
                    send_telegram_message(chat_id, text="Cú pháp sai. Dùng: `/autonotify on` hoặc `/autonotify off`.", reply_to_message_id=msg_id)
        
        elif cmd == '/event':
            temp_msg_id = send_telegram_message(chat_id, text="🔍 Đang tìm sự kiện airdrop...", reply_to_message_id=msg_id)
            if temp_msg_id:
                result = get_airdrop_events()
                
                # --- THAY ĐỔI LOGIC TẠO NÚT BẤM TẠI ĐÂY ---
                # Tạo một bàn phím với 2 nút trên cùng một hàng
                reply_markup = {
                    'inline_keyboard': [
                        [ # Hàng đầu tiên
                            {'text': '🔄 Refresh', 'callback_data': 'refresh_events'},
                            {'text': '🚀 Trade on Hyperliquid', 'url': 'https://app.hyperliquid.xyz/join/TIEUBOCHET'}
                        ]
                    ]
                }
                
                # Sửa tin nhắn "Đang tìm..." với kết quả và BÀN PHÍM MỚI
                edit_telegram_message(chat_id, temp_msg_id, text=result, reply_markup=json.dumps(reply_markup))
        
    if len(parts) == 1 and is_crypto_address(parts[0]):
        send_telegram_message(chat_id, text=find_token_across_networks(parts[0]), reply_to_message_id=msg_id, disable_web_page_preview=True)
    else:
        portfolio_result = process_portfolio_text(text)
        if portfolio_result:
            refresh_btn = {'inline_keyboard': [[{'text': '🔄 Refresh', 'callback_data': 'refresh_portfolio'}]]}
            send_telegram_message(chat_id, text=portfolio_result, reply_to_message_id=msg_id, reply_markup=json.dumps(refresh_btn))
        #else:
            #send_telegram_message(chat_id, text="🤔 Cú pháp không hợp lệ. Gửi /start để xem hướng dẫn.", reply_to_message_id=msg_id)
    return jsonify(success=True)
def check_events_and_notify_groups():
    """
    Kiểm tra các sự kiện airdrop và gửi thông báo + ghim tin nhắn
    cho tất cả các nhóm đã đăng ký.
    """
    if not kv:
        print("Event check skipped: No DB connection.")
        return 0

    print(f"[{datetime.now()}] Running group event notification check...")
    events, error = _get_processed_airdrop_events()
    if error or not events:
        print(f"Could not fetch events for notification: {error or 'No events found.'}")
        return 0

    notifications_sent = 0
    now = datetime.now(TIMEZONE)
    
    subscribers = kv.smembers("event_notification_groups")
    if not subscribers:
        print("Event check skipped: No subscribed groups.")
        return 0

    for event in events:
        event_time = event.get('effective_dt')
        if not event_time: continue

        if event_time > now:
            time_until_event = event_time - now
            
            if timedelta(minutes=0) < time_until_event <= timedelta(minutes=REMINDER_THRESHOLD_MINUTES):
                event_id = f"{event.get('token')}-{event_time.isoformat()}"
                
                for chat_id in subscribers:
                    redis_key = f"event_notified:{chat_id}:{event_id}"

                    if not kv.exists(redis_key):
                        minutes_left = int(time_until_event.total_seconds() // 60) + 1
                        token, name = event.get('token', 'N/A'), event.get('name', 'N/A')
                        
                        message = (f"‼️ *THÔNG BÁO* ‼️\n\n"
                                   f"Sự kiện: *{name} ({token})*\n"
                                   f"Sẽ diễn ra trong vòng *{minutes_left} phút* nữa.")
                        
                        sent_message_id = send_telegram_message(chat_id, text=message)
                        
                        if sent_message_id:
                            # Chỉ ghim tin nhắn nếu gửi thành công
                            pin_telegram_message(chat_id, sent_message_id)
                            notifications_sent += 1
                            # Đánh dấu đã thông báo, key tự xóa sau 1 giờ để dọn dẹp
                            kv.set(redis_key, "1", ex=3600)

    print(f"Group event notification check finished. Sent: {notifications_sent} notifications.")
    return notifications_sent

@app.route('/check_events', methods=['POST'])
def event_cron_webhook():
    """Endpoint để cron job gọi đến để kiểm tra sự kiện airdrop."""
    if not kv or not BOT_TOKEN or not CRON_SECRET:
        return jsonify(error="Server not configured"), 500
    
    secret = request.headers.get('X-Cron-Secret') or (request.is_json and request.get_json().get('secret'))
    if secret != CRON_SECRET:
        return jsonify(error="Unauthorized"), 403

    sent_count = check_events_and_notify_groups()
    return jsonify(success=True, notifications_sent=sent_count)
