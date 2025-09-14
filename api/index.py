# File: api/index.py
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

# --- KẾT NỐI CƠ SỞ DỮ LIỆU ---
kv = None
try:
    kv_url = os.getenv("REDIS_URL")
    if not kv_url: raise ValueError("REDIS_URL is not set.")
    kv = Redis.from_url(kv_url, decode_responses=True)
except Exception as e:
    print(f"FATAL: Could not connect to Redis. Error: {e}")

# --- LOGIC QUẢN LÝ CÔNG VIỆC ---
def _get_processed_airdrop_events():
    AIRDROP_API_URL = "https://alpha123.uk/api/data?fresh=1"
    PRICE_API_URL = "https://alpha123.uk/api/price/?batch=today"
    HEADERS = {
      'referer': 'https://alpha123.uk/index.html',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    def _get_price_data():
        try:
            res = requests.get(PRICE_API_URL, headers=HEADERS, timeout=10)
            res.raise_for_status()
            price_json = res.json()
            if price_json.get('success') and 'prices' in price_json:
                return price_json['prices']
        except requests.RequestException: pass
        return {}

    def _filter_and_deduplicate_events(events):
        processed = {}
        for event in events:
            key = (event.get('date'), event.get('token'))
            if key not in processed or event.get('phase', 1) > processed[key].get('phase', 1):
                processed[key] = event
        return list(processed.values())

    def _get_effective_event_time(event):
        event_date_str, event_time_str = event.get('date'), event.get('time')
        if not (event_date_str and event_time_str and ':' in event_time_str): return None
        try:
            cleaned_time_str = event_time_str.strip().split()[0]
            naive_dt = datetime.strptime(f"{event_date_str} {cleaned_time_str}", '%Y-%m-%d %H:%M')
            if event.get('phase') == 2: naive_dt += timedelta(hours=18)
            return CHINA_TIMEZONE.localize(naive_dt).astimezone(TIMEZONE)
        except (ValueError, pytz.exceptions.PyTZError): return None

    try:
        airdrop_res = requests.get(AIRDROP_API_URL, headers=HEADERS, timeout=20)
        if airdrop_res.status_code != 200: return None, f"❌ API Error (Code: {airdrop_res.status_code})."
        data = airdrop_res.json()
        airdrops = data.get('airdrops', [])
        if not airdrops: return [], None
        price_data = _get_price_data()
        definitive_events = _filter_and_deduplicate_events(airdrops)
        for event in definitive_events:
            event['effective_dt'] = _get_effective_event_time(event)
            event['price_data'] = price_data
        return definitive_events, None
    except requests.RequestException: return None, "❌ Network error when fetching data."
    except json.JSONDecodeError: return None, "❌ Invalid data format from API."

def get_airdrop_events() -> tuple[str, str | None]:
    processed_events, error_message = _get_processed_airdrop_events()
    if error_message: return error_message, None
    if not processed_events: return "ℹ️ No airdrop events found.", None

    def _format_event_message(event, price_data, effective_dt, include_date=False):
        token, name = event.get('token', 'N/A'), event.get('name', 'N/A')
        points, amount_str = event.get('points') or '-', event.get('amount') or '-'
        display_time = event.get('time') or 'TBA'
        if effective_dt and not any(x in display_time for x in ["Tomorrow", "Day after"]):
            time_part = effective_dt.strftime('%H:%M')
            display_time = f"{time_part} {effective_dt.strftime('%d/%m')}" if include_date else time_part
        price_str, value_str = "", ""
        if token in price_data:
            price_value = price_data[token].get('dex_price') or price_data[token].get('price', 0)
            if price_value > 0:
                price_str = f" (`${price_value:,.4f}`)"
                try: value_str = f"\n  Value: `${float(amount_str) * price_value:,.2f}`"
                except (ValueError, TypeError): pass
        return f"*{name} ({token})*{price_str}\n  Điểm: `{points}` \n  Số lượng: `{amount_str}`{value_str}\n  Thời gian: `{display_time}`"

    now_vietnam = datetime.now(TIMEZONE)
    today_date = now_vietnam.date()
    todays_events, upcoming_events = [], []
    for event in processed_events:
        effective_dt = event.get('effective_dt')
        if effective_dt and effective_dt < now_vietnam: continue
        try: event_day = effective_dt.date() if effective_dt else datetime.strptime(event.get('date'), '%Y-%m-%d').date()
        except (ValueError, TypeError): continue
        if event_day == today_date: todays_events.append(event)
        elif event_day > today_date: upcoming_events.append(event)
    
    todays_events.sort(key=lambda x: x.get('effective_dt') or datetime.max.replace(tzinfo=TIMEZONE))
    upcoming_events.sort(key=lambda x: x.get('effective_dt') or datetime.max.replace(tzinfo=TIMEZONE))
    
    message_parts, price_data = [], processed_events[0]['price_data'] if processed_events else {}
    if todays_events: message_parts.append("\n🎁 *Airdrops Hôm Nay:*\n\n" + "\n\n".join([_format_event_message(e, price_data, e['effective_dt']) for e in todays_events]))
    if upcoming_events:
        if message_parts: message_parts.append("\n\n" + "-"*25 + "\n\n")
        message_parts.append("\n🗓️ *Airdrops Sắp Tới:*\n\n" + "\n\n".join([_format_event_message(e, price_data, e['effective_dt'], True) for e in upcoming_events]))
    
    final_message = "".join(message_parts) if message_parts else "ℹ️ Không có sự kiện nào sắp tới."
    
    # --- THÊM DÒNG CHỮ MỚI TẠI ĐÂY ---
    # Chỉ thêm tin nhắn ref khi có sự kiện được hiển thị
    if message_parts:
        promo_text = "\n\n*Đăng ký qua link ref bên dưới để vừa hỗ trợ mình, vừa nhận thêm GIẢM 4% PHÍ trade cho bạn. Win – Win cùng nhau!*"
        final_message += promo_text

    # Tìm token của sự kiện gần nhất
    next_event_token = None
    if todays_events:
        next_event_token = todays_events[0].get('token')
    elif upcoming_events:
        next_event_token = upcoming_events[0].get('token')

    return final_message, next_event_token

# --- HÀM HỖ TRỢ TELEGRAM ---
def send_telegram_message(chat_id, text, **kwargs):
    if not BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown', **kwargs}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200 and response.json().get('ok'): return response.json().get('result', {}).get('message_id')
        print(f"Error sending message: {response.text}")
    except requests.RequestException as e: print(f"Error sending message: {e}")

def pin_telegram_message(chat_id, message_id):
    if not BOT_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/pinChatMessage", json={'chat_id': chat_id, 'message_id': message_id, 'disable_notification': False}, timeout=10)

def edit_telegram_message(chat_id, msg_id, text, **kwargs):
    if not BOT_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText", json={'chat_id': chat_id, 'message_id': msg_id, 'text': text, 'parse_mode': 'Markdown', **kwargs}, timeout=10)

def answer_callback_query(cb_id):
    if not BOT_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={'callback_query_id': cb_id}, timeout=5)

# --- WEB SERVER (FLASK) ---
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def telegram_webhook():
    if request.method == 'GET':
        return "Webhook is active.", 200

    if not BOT_TOKEN: return "Server config error", 500
    
    data = request.get_json()
    if "callback_query" in data:
        cb = data["callback_query"]
        answer_callback_query(cb["id"])
        if cb.get("data") == "refresh_events":
            new_text, next_token = get_airdrop_events()
            
            button_text = '🚀 Trade on Hyperliquid'
            if next_token:
                button_text = f'🚀 Trade {next_token.upper()} on Hyperliquid'

            new_reply_markup = {'inline_keyboard': [[{'text': button_text, 'url': 'https://app.hyperliquid.xyz/join/TIEUBOCHET'}]]}
            
            if new_text != cb["message"]["text"] or json.dumps(new_reply_markup) != json.dumps(cb["message"].get("reply_markup")):
                edit_telegram_message(
                    cb["message"]["chat"]["id"], 
                    cb["message"]["message_id"], 
                    text=new_text, 
                    reply_markup=json.dumps(new_reply_markup)
                )
        return jsonify(success=True)

    if not data or "message" not in data or "text" not in data["message"]: return jsonify(success=True)
    
    message = data["message"]
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    cmd = message["text"].strip().split()[0].lower()

    if cmd == '/start':
        start_message = "Bot Airdrop Alpha đã sẵn sàng!\n\n`/alpha` - Xem sự kiện.\n`/stop` - Dừng bot & tắt thông báo."
        send_telegram_message(chat_id, text=start_message)
        if kv:
            kv.sadd("event_notification_groups", str(chat_id))
            send_telegram_message(chat_id, text="✅ Đã bật thông báo tự động.")
        else:
            send_telegram_message(chat_id, text="⚠️ Lỗi DB, không thể bật thông báo.")

    elif cmd == '/stop':
        if kv:
            kv.srem("event_notification_groups", str(chat_id))
            send_telegram_message(chat_id, text="✅ Đã tắt thông báo tự động.")
        else:
            send_telegram_message(chat_id, text="❌ Lỗi DB, không thể tắt thông báo.")

    elif cmd == '/alpha':
        temp_msg_id = send_telegram_message(chat_id, text="🔍 Đang tìm sự kiện...", reply_to_message_id=msg_id)
        if temp_msg_id:
            result, next_token = get_airdrop_events()
            
            button_text = '🚀 Trade on Hyperliquid'
            if next_token:
                button_text = f'🚀 Trade {next_token.upper()} on Hyperliquid'
            
            reply_markup = {'inline_keyboard': [[{'text': button_text, 'url': 'https://app.hyperliquid.xyz/join/TIEUBOCHET'}]]}
            edit_telegram_message(chat_id, temp_msg_id, text=result, reply_markup=json.dumps(reply_markup))
    
    return jsonify(success=True)

@app.route('/check_events', methods=['POST'])
def cron_job_handler():
    # --- Phần xác thực giữ nguyên ---
    if not all([kv, BOT_TOKEN, CRON_SECRET]): 
        return jsonify(error="Server not configured"), 500
    if request.headers.get('X-Cron-Secret') != CRON_SECRET: 
        return jsonify(error="Unauthorized"), 403
    
    # --- LOGIC GIẢ LẬP VÀ TEST ---
    real_now = datetime.now(TIMEZONE) # Luôn lấy thời gian thật
    now = real_now # Mặc định 'now' để xử lý là thời gian thật
    
    is_test_mode = request.args.get('test_next_event') == 'true'
    fake_time_str = request.args.get('fake_time')

    if is_test_mode:
        print(f"--- TEST MODE ACTIVATED ---")
        # Chế độ test này sẽ ghi đè lên fake_time nếu có
        events, error = _get_processed_airdrop_events()
        if not error and events:
            # Tìm sự kiện gần nhất trong tương lai
            future_events = sorted(
                [e for e in events if e.get('effective_dt') and e.get('effective_dt') > real_now],
                key=lambda x: x['effective_dt']
            )
            
            if future_events:
                next_event = future_events[0]
                event_time = next_event.get('effective_dt')
                # Giả lập 'now' là 4 phút trước khi sự kiện diễn ra
                now = event_time - timedelta(minutes=4)
                print(f"Found next event: {next_event.get('token')} at {event_time.isoformat()}")
                print(f"SUCCESS: Simulating current time as: {now.isoformat()}")
            else:
                print("WARNING: Test mode enabled, but no future events found to test.")
        else:
            print("WARNING: Test mode enabled, but could not fetch events.")
            
    elif fake_time_str:
        print(f"--- FAKE TIME MODE ACTIVATED ---")
        try:
            naive_dt = datetime.strptime(fake_time_str, '%Y-%m-%d-%H-%M')
            now = TIMEZONE.localize(naive_dt)
            print(f"SUCCESS: Using fake time: {now.isoformat()}")
        except ValueError:
            print(f"WARNING: Invalid fake_time format. Falling back to real time.")
    else:
        print(f"Using real time: {now.isoformat()}")
    # --- KẾT THÚC LOGIC GIẢ LẬP ---

    # --- Phần logic chính của Cron Job giữ nguyên ---
    events, error = _get_processed_airdrop_events()
    if error or not events:
        print(f"Cron: Could not fetch events: {error or 'No events found.'}")
        return jsonify(success=True, notifications_sent=0)
    
    notifications_sent = 0
    subscribers = kv.smembers("event_notification_groups")
    if not subscribers: 
        return jsonify(success=True, notifications_sent=0)

    for event in events:
        event_time = event.get('effective_dt')
        if not event_time or not (now < event_time <= now + timedelta(minutes=REMINDER_THRESHOLD_MINUTES)): 
            continue
        
        print(f"MATCH FOUND! Event: {event.get('token')} at {event_time.isoformat()}. Current time: {now.isoformat()}")
        event_id = f"{event.get('token')}-{event_time.isoformat()}"
        for chat_id in subscribers:
            redis_key = f"event_notified:{chat_id}:{event_id}"
            if not kv.exists(redis_key):
                minutes_left = int((event_time - now).total_seconds() / 60) + 1
                message = f"‼️ *THÔNG BÁO* ‼️\n\nSự kiện: *{event.get('name', 'N/A')} ({event.get('token', 'N/A')})*\nSẽ diễn ra trong vòng *{minutes_left} phút* nữa."
                sent_message_id = send_telegram_message(chat_id, text=message)
                if sent_message_id:
                    pin_telegram_message(chat_id, sent_message_id)
                    notifications_sent += 1
                    kv.set(redis_key, "1", ex=3600)
    
    print(f"Cron check finished. Sent: {notifications_sent} notifications.")
    return jsonify(success=True, notifications_sent=notifications_sent, used_time=now.isoformat())