import os
import time
import json
import asyncio
import httpx
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# ==================== CONFIG & ENV ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 10000))

# Разрешенные инструменты (как на Pocket Option / Binarium)
SUPPORTED_ASSETS = [
    "XAUUSD", "XAUUSD_otc",       # Золото
    "EURUSD", "EURUSD_otc",
    "GBPUSD", "GBPUSD_otc",
    "USDJPY", "USDJPY_otc",
    "EURJPY", "EURJPY_otc",
    "AUDUSD", "AUDUSD_otc",
    "USDCHF", "USDCHF_otc",
    "NZDUSD", "NZDUSD_otc",
    "GBPJPY", "GBPJPY_otc"
]

# Глобальное хранилище для приёма вебхуков от TradingView
last_signals = {}

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BRODYAGA TV WEBHOOK BOT is running successfully!")

    def do_POST(self):
        global last_signals
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            symbol = data.get("symbol", "").upper().strip()
            action = data.get("action", "").upper().strip()  # CALL / PUT или LONG / SHORT
            rsi = data.get("rsi", "N/A")
            tf = data.get("tf", "5m")

            if symbol not in SUPPORTED_ASSETS:
                self._send_response(400, "Invalid asset")
                return

            # Защита от дубликатов (интервал 60 секунд на один актив)
            now = time.time()
            if symbol in last_signals and now - last_signals[symbol] < 60:
                self._send_response(200, "Signal skipped (throttle)")
                return
            last_signals[symbol] = now

            # Форматирование направления
            if action in ["LONG", "CALL", "BUY"]:
                direction = "CALL 🟢 (ВВЕРХ)"
            else:
                direction = "PUT 🔴 (ВНИЗ)"

            clean_sym = symbol.replace("_otc", " OTC").upper()
            t_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

            # Отправка в Telegram
            msg = (
                f"🔥 **BRODYAGA TV SIGNAL** 🔥\n\n"
                f"📊 Актив: `{clean_sym}`\n"
                f"🎯 Направление: **{direction}**\n"
                f"📈 RSI: `{rsi}`\n"
                f"⏱ Таймфрейм: `{tf}`\n"
                f"⏰ Время: `{t_str}`\n"
                f"⏳ Экспирация: `2-5 мин`"
            )
            send_telegram(msg)

            self._send_response(200, "Signal processed")
        except Exception as e:
            print(f"Webhook parse error: {e}")
            self._send_response(400, "Bad Request")

    def _send_response(self, code, message):
        self.send_response(code)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

    def log_message(self, *args):
        return  # Отключаем лишний мусор в логах сервера

def send_telegram(msg):
    if not BOT_TOKEN or not CHANNEL_ID:
        print(f"[PREVIEW TELEGRAM]:\n{msg}\n")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        httpx.post(url, json={"chat_id": CHANNEL_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")

if __name__ == "__main__":
    print(f"🤖 Brodyaga Webhook Server starting on port {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    server.serve_forever()
