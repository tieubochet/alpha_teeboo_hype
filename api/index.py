import os
import json
import requests
from flask import Flask, request, jsonify
from redis import Redis

app = Flask(__name__)

# --- CẤU HÌNH ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRON_SECRET = os.getenv("CRON_SECRET")

try:
    kv_url = os.getenv("REDIS_URL")
    kv = Redis.from_url(kv_url, decode_responses=True) if kv_url else None
except Exception as e:
    print(f"Lỗi kết nối Redis: {e}")
    kv = None

# --- HYPERLIQUID API ---
def get_hl_positions(wallet_address):
    """Gọi API Hyperliquid để lấy danh sách vị thế hiện tại của ví"""
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "clearinghouseState", "user": wallet_address}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            return None
        
        data = res.json()
        positions = {}
        # Duyệt qua các tài sản đang có vị thế
        for asset in data.get("assetPositions", []):
            pos = asset.get("position", {})
            coin = pos.get("coin")
            szi = float(pos.get("szi", 0))  # Kích thước vị thế (dương: Long, âm: Short)
            
            if szi != 0:
                positions[coin] = {
                    "szi": szi,
                    "entryPx": float(pos.get("entryPx", 0)),
                    "leverage": pos.get("leverage", {}).get("value", 0)
                }
        return positions
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu Hyperliquid cho ví {wallet_address}: {e}")
        return None

# --- TELEGRAM API ---
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id, 
        'text': text, 
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi tin nhắn: {e}")

# --- WEBHOOK CHO BOT TELEGRAM ---
@app.route('/', methods=['POST'])
def webhook():
    if not kv:
        return jsonify(error="Chưa kết nối Redis"), 500

    data = request.get_json()
    if "message" not in data or "text" not in data["message"]: 
        return jsonify(success=True)
    
    chat_id = data["message"]["chat"]["id"]
    text = data["message"]["text"].strip()
    parts = text.split()
    cmd = parts[0].lower()

    if cmd == "/start":
        msg = ("🤖 *Hyperliquid Tracker Bot*\n\n"
               "Quản lý theo dõi ví mở vị thế trên Hyperliquid.\n\n"
               "🔹 `/add <địa chỉ ví>` - Thêm ví để theo dõi\n"
               "🔹 `/remove <địa chỉ ví>` - Xóa ví khỏi danh sách\n"
               "🔹 `/list` - Xem các ví đang theo dõi")
        send_telegram_message(chat_id, msg)

    elif cmd == "/add" and len(parts) == 2:
        wallet = parts[1].lower()
        kv.sadd(f"user:{chat_id}:wallets", wallet)
        kv.sadd(f"wallet:{wallet}:subs", str(chat_id))
        kv.sadd("all_tracked_wallets", wallet)
        send_telegram_message(chat_id, f"✅ Đã thêm ví `{wallet}` vào danh sách theo dõi.")

    elif cmd == "/remove" and len(parts) == 2:
        wallet = parts[1].lower()
        kv.srem(f"user:{chat_id}:wallets", wallet)
        kv.srem(f"wallet:{wallet}:subs", str(chat_id))
        send_telegram_message(chat_id, f"❌ Đã ngừng theo dõi ví `{wallet}`.")

    elif cmd == "/list":
        wallets = kv.smembers(f"user:{chat_id}:wallets")
        if wallets:
            msg = "📋 *Danh sách ví bạn đang theo dõi:*\n\n" + "\n".join([f"- `{w}`" for w in wallets])
        else:
            msg = "⚠️ Bạn chưa theo dõi ví nào."
        send_telegram_message(chat_id, msg)

    return jsonify(success=True)

# --- CRONJOB KIỂM TRA VỊ THẾ ---
@app.route('/check_positions', methods=['GET', 'POST'])
def check_positions():
    if not kv:
        return jsonify(error="Chưa kết nối Redis"), 500

    # Xác thực Cronjob từ Vercel (Hỗ trợ header Authorization của Vercel Cron hoặc custom header)
    auth_header = request.headers.get('Authorization')
    custom_header = request.headers.get('X-Cron-Secret')
    is_authorized = (auth_header == f"Bearer {CRON_SECRET}") or (custom_header == CRON_SECRET)
    
    if not is_authorized:
        return jsonify(error="Unauthorized"), 403

    wallets = kv.smembers("all_tracked_wallets")
    notifications_sent = 0

    for wallet in wallets:
        subs = kv.smembers(f"wallet:{wallet}:subs")
        if not subs:
            kv.srem("all_tracked_wallets", wallet) # Dọn dẹp nếu không ai theo dõi ví này nữa
            continue
            
        current_pos = get_hl_positions(wallet)
        if current_pos is None:
            continue
            
        prev_pos_str = kv.get(f"hl_pos:{wallet}")
        prev_pos = json.loads(prev_pos_str) if prev_pos_str else {}
        
        # So sánh để tìm vị thế mới được mở
        for coin, data in current_pos.items():
            if coin not in prev_pos:
                direction = "🟢 LONG" if data["szi"] > 0 else "🔴 SHORT"
                msg = (f"🚨 *Vị thế mới trên Hyperliquid!*\n\n"
                       f"👤 Ví: `{wallet[:6]}...{wallet[-4:]}`\n"
                       f"🪙 Token: *{coin}*\n"
                       f"📈 Hướng: {direction}\n"
                       f"💰 Size: `{abs(data['szi'])}`\n"
                       f"🎯 Entry: `${data['entryPx']}`\n"
                       f"⚡ Đòn bẩy: `{data['leverage']}x`\n\n"
                       f"[👉 Trade {coin} trên Hyperliquid](https://app.hyperliquid.xyz/trade/{coin})")
                
                for chat_id in subs:
                    send_telegram_message(chat_id, msg)
                    notifications_sent += 1
                    
        # Lưu lại trạng thái vị thế mới nhất
        kv.set(f"hl_pos:{wallet}", json.dumps(current_pos))

    return jsonify(status="success", notifications_sent=notifications_sent)