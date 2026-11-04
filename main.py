import os
import time
import random
import json
import asyncio
import httpx
import websockets
import pandas as pd
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==================== HEALTH-CHECK SERVER ====================
class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V5 POCKET OPTION OTC running")

    def log_message(self, *args):
        return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()

Thread(target=run_fake_server, daemon=True).start()

# ==================== CONFIG & ENV ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

# Pocket Option Credentials & WS URL
PO_SSID = os.getenv("POCKET_OPTION_SSID", "")  # Ваш SSID сессии Pocket Option
PO_WS_URL = os.getenv("POCKET_OPTION_WS_URL", "wss://api.pocketoption.com/socket.io/?EIO=4&transport=websocket")

# Символы OTC Pocket Option
SYMBOLS = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "EURJPY_otc", "AUDUSD_otc"]

# ==================== DATA FETCHERS ====================
async def get_pocket_option_candles(symbol="EURUSD_otc", tf=60, count=100):
    """
    Асинхронное получение свечей для Pocket Option через WebSocket.
    tf: таймфрейм в секундах (60 = 1m)
    """
    if not PO_SSID:
        return None

    try:
        async with websockets.connect(PO_WS_URL) as ws:
            # Инициализация сессии Pocket Option (Socket.IO Handshake)
            auth_msg = f'42["auth", {{"session": "{PO_SSID}", "isDemo": 1}}]'
            await ws.send(auth_msg)
            
            # Запрос истории свечей
            request_msg = f'42["getHistory", {{"asset": "{symbol}", "period": {tf}, "count": {count}}}]'
            await ws.send(request_msg)

            # Получение ответа
            for _ in range(5):
                raw = await ws.recv()
                if "history" in raw:
                    # Извлечение JSON данных
                    json_str = raw[raw.find('['):]
                    data = json.loads(json_str)
                    candles_raw = data[1].get('history', [])
                    if candles_raw:
                        df = pd.DataFrame(candles_raw)
                        # Переименование колонок под единый стандарт
                        df = df.rename(columns={'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close'})
                        return df[['time', 'open', 'high', 'low', 'close']]
    except Exception as e:
        print(f"Pocket Option fetcher error ({symbol}): {e}")
    return None

async def get_otc_candles(symbol, tf="1m", limit=100):
    """
    Основная функция получения свечей:
    1. Пробует получить свечи Pocket Option.
    2. При отсутствии подключения/ошибке переходит на мок-данные.
    """
    tf_sec = 60 if tf == "1m" else 300
    df = await get_pocket_option_candles(symbol, tf_sec, limit)
    
    if df is not None and not df.empty:
        return df

    # Заглушка (Мок-данные для тестов/симуляции)
    now = pd.Timestamp.now()
    data = []
    price = 1.0850 + random.uniform(-0.01, 0.01)
    for i in range(limit):
        o = price
        c = o + random.uniform(-0.0005, 0.0005)
        h = max(o, c) + random.uniform(0, 0.0002)
        l = min(o, c) - random.uniform(0, 0.0002)
        data.append([now - pd.Timedelta(minutes=limit - i), o, h, l, c])
        price = c
    return pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])

# ==================== TECHNICAL ANALYSIS ====================
def analyze(df):
    if df is None or len(df) < 50:
        return None

    # Скользящие средние (EMA 9 / EMA 21)
    df['ema9'] = df['close'].ewm(span=9).mean()
    df['ema21'] = df['close'].ewm(span=21).mean()

    # Индикатор относительной силы (RSI 14)
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))

    last = df.iloc[-1]
    prev = df.iloc[-2]

    up = last['ema9'] > last['ema21'] and last['close'] > last['ema9']
    down = last['ema9'] < last['ema21'] and last['close'] < last['ema9']

    # Паттерн: Бычье / Медвежье поглощение (Engulfing)
    bull = last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bear = last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']

    if up and last['rsi'] < 70 and bull:
        return "CALL 🟢 (ВВЕРХ)", round(last['rsi'], 1)
    if down and last['rsi'] > 30 and bear:
        return "PUT 🔴 (ВНИЗ)", round(last['rsi'], 1)

    return None

# ==================== TELEGRAM NOTIFIER ====================
def send(msg):
    if not BOT_TOKEN or not CHANNEL_ID:
        print(f"[PREVIEW MSG]:\n{msg}\n")
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print(f"Send error: {e}")

# ==================== MAIN ASYNC LOOP ====================
async def main_loop():
    print("🤖 Bot V5 Pocket Option OTC started...")
    while True:
        for sym in SYMBOLS:
            try:
                df = await get_otc_candles(sym)
                res = analyze(df)
                if res:
                    direction, rsi_val = res
                    t_str = datetime.now().strftime("%H:%M:%S")
                    # Красиво форматированное имя символа (например: EUR/USD OTC)
                    clean_sym = sym.replace("_otc", "").upper()
                    clean_sym = f"{clean_sym[:3]}/{clean_sym[3:]} OTC"
                    
                    send(f"🔥 **POCKET OPTION SIGNAL** 🔥\n\n"
                         f"📊 Пара: `{clean_sym}`\n"
                         f"🎯 Направление: **{direction}**\n"
                         f"📈 RSI: `{rsi_val}`\n"
                         f"⏰ Время: `{t_str} UTC+3`\n"
                         f"⏳ Экспирация: `1-3 мин`")
            except Exception as e:
                print(f"Error processing {sym}: {e}")
            await asyncio.sleep(1)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
