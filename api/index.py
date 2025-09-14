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
    kv_url = os.getenv("teeboov2_REDIS_URL")
    if not kv_url: raise ValueError("teeboov2_REDIS_URL is not set.")
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

def get_airdrop_events() -> str:
    processed_events, error_message = _get_processed_airdrop_events()
    if error_message: return error_message
    if not processed_events: return "ℹ️ No airdrop events found."

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
        return f"*{token} - {name}*{price_str}\n  Points: `{points}` | Amount: `{amount_str}`{value_str}\n  Time: `{display_time}`"

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
    if todays_events: message_parts.append("🎁 *Today's Airdrops:*\n\n" + "\n\n".join([_format_event_message(e, price_data, e['effective_dt']) for e in todays_events]))
    if upcoming_events:
        if message_parts: message_parts.append("\n\n" + "-"*25 + "\n\n")
        message_parts.append("🗓️ *Upcoming Airdrops:*\n\n" + "\n\n".join([_format_event_message(e, price_data, e['effective_dt'], True) for e in upcoming_events]))
    
    return "".join(message_parts) if message_parts else "ℹ️ No upcoming events."

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

# THAY ĐỔI 1: Tách route chính và cho phép cả GET và POST
@app.route('/', methods=['GET', 'POST'])
def telegram_webhook():
    # Xử lý yêu cầu GET từ Telegram/Vercel
    if request.method == 'GET':
        return "Webhook is active.", 200

    # Xử lý yêu cầu POST từ Telegram
    if not BOT_TOKEN: return "Server config error", 500
    
    data = request.get_json()
    if "callback_query" in data:
        cb = data["callback_query"]
        answer_callback_query(cb["id"])
        if cb.get("data") == "refresh_events":
            new_text = get_airdrop_events()
            if new_text != cb["message"]["text"]:
                edit_telegram_message(cb["message"]["chat"]["id"], cb["message"]["message_id"], text=new_text, reply_markup=json.dumps(cb["message"]["reply_markup"]))
        return jsonify(success=True)

    if not data or "message" not in data or "text" not in data["message"]: return jsonify(success=True)
    
    message = data["message"]
    chat_id, msg_id = message["chat"]["id"], message["message_id"]
    cmd = message["text"].strip().split()[0].lower()

    if cmd == '/start':
        start_message = "Bot Airdrop Alpha đã sẵn sàng!\n\n🔹 `/alpha` - Xem sự kiện.\n🔹 `/stop` - Tắt thông báo."
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
            result = get_airdrop_events()
            reply_markup = {'inline_keyboard': [[{'text': '🔄 Refresh', 'callback_data': 'refresh_events'}, {'text': '🚀 Trade on Hyperliquid', 'url': 'https://app.hyperliquid.xyz/join/TIEUBOCHET'}]]}
            edit_telegram_message(chat_id, temp_msg_id, text=result, reply_markup=json.dumps(reply_markup))
    
    return jsonify(success=True)

# THAY ĐỔI 2: Tạo một route riêng chỉ cho Cron Job
@app.route('/check_events', methods=['POST'])
def cron_job_handler():
    if not all([kv, BOT_TOKEN, CRON_SECRET]): return jsonify(error="Server not configured"), 500
    if request.headers.get('X-Cron-Secret') != CRON_SECRET: return jsonify(error="Unauthorized"), 403
    
    # --- Logic của Cron Job ---
    events, error = _get_processed_airdrop_events()
    if error or not events:
        print(f"Cron: Could not fetch events: {error or 'No events found.'}")
        return jsonify(success=True, notifications_sent=0)
    
    notifications_sent = 0
    now = datetime.now(TIMEZONE)
    subscribers = kv.smembers("event_notification_groups")
    if not subscribers: return jsonify(success=True, notifications_sent=0)

    for event in events:
        event_time = event.get('effective_dt')
        if not event_time or not (now < event_time <= now + timedelta(minutes=REMINDER_THRESHOLD_MINUTES)): continue
        
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
    return jsonify(success=True, notifications_sent=notifications_sent)