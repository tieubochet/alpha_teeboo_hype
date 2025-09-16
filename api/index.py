import os
import json
import requests
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

FOOTER_MESSAGE = "\n\n-------------------------\n\n*Đăng ký qua link ref bên dưới để vừa hỗ trợ mình, vừa nhận thêm GIẢM 4% PHÍ trade cho bạn. Win – Win cùng nhau!*"

# --- KẾT NỐI CƠ SỞ DỮ LIỆU ---
try:
    kv_url = os.getenv("REDIS_URL")
    if not kv_url: raise ValueError("REDIS_URL is not set.")
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

    def _get_effective_event_time(event):
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
        
        for event in airdrops:
            event['effective_dt'] = _get_effective_event_time(event)
            event['price_data'] = price_data

        return airdrops, None
    except requests.RequestException: return None, "❌ Lỗi mạng khi lấy dữ liệu sự kiện."
    except json.JSONDecodeError: return None, "❌ Dữ liệu trả về từ API sự kiện không hợp lệ."

def _get_SIMULATED_airdrop_events():
    """
    HÀM GIẢ LẬP: Tạo ra một sự kiện giả sẽ diễn ra sau 4 phút nữa.
    Chỉ dùng để kiểm tra cron job.
    """
    print("--- RUNNING IN SIMULATION MODE ---")
    
    # Tạo thời điểm trong tương lai gần (4 phút kể từ bây giờ)
    # Điều này đảm bảo nó nằm trong ngưỡng 5 phút của REMINDER_THRESHOLD_MINUTES
    event_time_vietnam = datetime.now(TIMEZONE) + timedelta(minutes=4)
    
    # Chuyển đổi về múi giờ Trung Quốc để tạo dữ liệu date/time giả
    event_time_china = event_time_vietnam.astimezone(CHINA_TIMEZONE)
    
    # Tạo một sự kiện giả với đầy đủ thông tin
    fake_event = {
        'token': 'TEST',
        'name': 'Cron Job Test Event',
        'points': '999',
        'amount': '123',
        'date': event_time_china.strftime('%Y-%m-%d'),
        'time': event_time_china.strftime('%H:%M'),
        'phase': 1,
        'effective_dt': event_time_vietnam, # Thời gian đã được tính toán
        'price_data': {
            "TEST": { "price": 10.0 } # Dữ liệu giá giả
        }
    }
    
    print(f"Simulated event created for time: {event_time_vietnam.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Trả về dữ liệu giống hệt như hàm thật
    return [fake_event], None

def format_event_for_display(event, price_data, effective_dt, include_date=False, include_time=True):
    """
    Hàm trợ giúp chung để định dạng một sự kiện thành chuỗi tin nhắn.
    - include_time: Tùy chọn để ẩn/hiện dòng "Thời gian".
    """
    token, name = event.get('token', 'N/A'), event.get('name', 'N/A')
    points, amount_str = event.get('points') or '-', event.get('amount') or '-'
    
    display_time = event.get('time') or 'TBA'
    is_special_time = "Tomorrow" in display_time or "Day after" in display_time
    
    if effective_dt and not is_special_time:
        time_part = effective_dt.strftime('%H:%M')
        if include_date:
            date_part = effective_dt.strftime('%d/%m')
            display_time = f"{time_part} {date_part}"
        else:
            display_time = time_part
    
    time_str = f"`{display_time}`"

    price_display = "N/A"
    value_line = ""
    if price_data and token in price_data:
        price_info = price_data.get(token, {})
        price_value = price_info.get('dex_price') or price_info.get('price', 0)
        if price_value > 0:
            price_display = f"${price_value:,.4f}"
            try:
                numeric_amount = float(str(amount_str).replace(',', ''))
                value = numeric_amount * price_value
                value_line = f"\n  Giá trị: `${value:,.2f}`"
            except (ValueError, TypeError): pass

    message = (f"*{name} ({token}): {price_display}*\n"
               f"  Điểm: `{points}`\n"
               f"  Số lượng: `{amount_str}`{value_line}")
    
    if include_time:
        message += f"\n  Thời gian: {time_str}"
        
    return message

def get_airdrop_events() -> tuple[str, str | None]:
    """
    Hàm giao diện: Gọi hàm logic cốt lõi và định dạng kết quả thành tin nhắn cho người dùng.
    Đồng thời trả về token của sự kiện sắp diễn ra gần nhất.
    """
    processed_events, error_message = _get_processed_airdrop_events()
    
    if error_message:
        return error_message + FOOTER_MESSAGE, None
    if not processed_events:
        return "ℹ️ Không tìm thấy sự kiện airdrop nào." + FOOTER_MESSAGE, None

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
    
    next_event_token = None
    if todays_events:
        next_event_token = todays_events[0].get('token')
    elif upcoming_events:
        next_event_token = upcoming_events[0].get('token')

    message_parts = []
    price_data = processed_events[0]['price_data'] if processed_events else {}
    
    if todays_events:
        today_messages = [format_event_for_display(e, price_data, e['effective_dt']) for e in todays_events]
        message_parts.append("🎁 *Today's Airdrops:*\n\n" + "\n\n".join(today_messages))

    if upcoming_events:
        if message_parts: message_parts.append("\n\n" + "-"*25 + "\n\n")
        upcoming_messages = [format_event_for_display(e, price_data, e['effective_dt'], include_date=True) for e in upcoming_events]
        message_parts.append("🗓️ *Upcoming Airdrops:*\n\n" + "\n\n".join(upcoming_messages))

    if not message_parts:
        final_message = "ℹ️ Không có sự kiện airdrop nào đáng chú ý trong hôm nay và các ngày sắp tới."
    else:
        final_message = "".join(message_parts)

    return final_message + FOOTER_MESSAGE, next_event_token

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

# --- WEB SERVER (FLASK) ---
app = Flask(__name__)
@app.route('/', methods=['POST'])
def webhook():
    if not BOT_TOKEN: return "Server configuration error", 500
    data = request.get_json()
    if "callback_query" in data:
        cb = data["callback_query"]; answer_callback_query(cb["id"])
        
        if cb.get("data") == "refresh_events":
            result_text, next_token = get_airdrop_events()
            old_text = cb["message"]["text"]
            
            if result_text != old_text:
                edit_telegram_message(
                    chat_id=cb["message"]["chat"]["id"],
                    msg_id=cb["message"]["message_id"],
                    text=result_text,
                    reply_markup=json.dumps(cb["message"]["reply_markup"])
                )
        return jsonify(success=True)

    if "message" not in data or "text" not in data["message"]: return jsonify(success=True)
    
    chat_id = data["message"]["chat"]["id"]
    msg_id = data["message"]["message_id"]
    text = data["message"]["text"].strip()
    
    if text.startswith('/'):
        cmd = text.split()[0].lower()

        if cmd == "/start":
            if kv:
                kv.sadd("event_notification_groups", str(chat_id))
                start_message = "✅ *Đã bật thông báo!*\n\n🔹 `/alpha` - Xem sự kiện.\n🔹 `/stop` - Tắt thông báo."
            else:
                start_message = "Bot Airdrop Alpha đã sẵn sàng!\n\n🔹 `/alpha` - Xem sự kiện.\n(Lỗi kết nối DB, tính năng thông báo có thể không hoạt động)"
            send_telegram_message(chat_id, text=start_message)

        elif cmd == "/stop":
            if kv:
                kv.srem("event_notification_groups", str(chat_id))
                stop_message = "❌ *Đã tắt thông báo!*"
                send_telegram_message(chat_id, text=stop_message)

        elif cmd == '/alpha':
            temp_msg_id = send_telegram_message(chat_id, text="🔍 Đang tìm sự kiện airdrop...", reply_to_message_id=msg_id)
            if temp_msg_id:
                result_text, next_token = get_airdrop_events()
                
                trade_button_url = "https://app.hyperliquid.xyz/join/TIEUBOCHET"
                
                if next_token:
                    token_symbol = next_token.upper()
                    trade_button_text = f"🚀 Trade {token_symbol} on Hyperliquid"
                else:
                    trade_button_text = "🚀 Trade on Hyperliquid"

                reply_markup = {
                    'inline_keyboard': [
                        [{'text': trade_button_text, 'url': trade_button_url}]
                    ]
                }
                
                edit_telegram_message(chat_id, temp_msg_id, text=result_text, reply_markup=json.dumps(reply_markup))

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
    events, error = _get_SIMULATED_airdrop_events()
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
                        token = event.get('token', 'N/A')
                        
                        detailed_event_info = format_event_for_display(
                            event, event['price_data'], event['effective_dt'], include_time=False
                        )

                        message = (f"‼️ *THÔNG BÁO*‼️\n\n"
                                   f"Sự kiện:\n{detailed_event_info}\n\n"
                                   f"sẽ diễn ra trong vòng *{minutes_left} phút* nữa."
                                   f"{FOOTER_MESSAGE}")
                        
                        token_symbol = token.upper()
                        trade_button_text = f"🚀 Trade {token_symbol} on Hyperliquid"
                        trade_button_url = "https://app.hyperliquid.xyz/join/TIEUBOCHET"

                        reply_markup = {
                            'inline_keyboard': [
                                [{'text': trade_button_text, 'url': trade_button_url}]
                            ]
                        }
                        
                        sent_message_id = send_telegram_message(
                            chat_id, 
                            text=message,
                            reply_markup=json.dumps(reply_markup)
                        )
                        
                        if sent_message_id:
                            pin_telegram_message(chat_id, sent_message_id)
                            notifications_sent += 1
                            kv.set(redis_key, "1", ex=3600)

    print(f"Group event notification check finished. Sent: {notifications_sent} notifications.")
    return notifications_sent

@app.route('/check_events', methods=['POST'])
def cron_webhook():
    if not kv or not BOT_TOKEN or not CRON_SECRET: return jsonify(error="Server not configured"), 500
    
    secret = request.headers.get('X-Cron-Secret')
    if secret != CRON_SECRET: return jsonify(error="Unauthorized"), 403
    
    notifications_sent = check_events_and_notify_groups()
    
    result = {"status": "success", "notifications_sent": notifications_sent}
    print(result)
    return jsonify(result)