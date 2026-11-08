import os
import time
import random
import json
import asyncio
import httpx
import websockets
import pandas as pd
from datetime import datetime, timezone
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V6 BRODYAGA running")
    def log_message(self, *args):
        return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()

Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PO_SSID = os.getenv("POCKET_OPTION_SSID", "")
PO_WS_URL = os.getenv("POCKET_OPTION_WS_URL", "wss://api.pocketoption.com/socket.io/?EIO=4&transport=websocket")

# ТВОЯ ТАКТИКА: Все пары
MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY", "AUDUSD", "USDCHF", "NZDUSD", "GBPJPY"]
OTC = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "EURJPY_otc", "AUDUSD_otc", "USDCHF_otc", "NZDUSD_otc", "GBPJPY_otc", "EURGBP_otc", "AUDCAD_otc"]

async def get_pocket_option_candles(symbol="EURUSD_otc", tf=60, count=100):
    if not PO_SSID:
        return None
    try:
        async with websockets.connect(PO_WS_URL) as ws:
            auth_msg = f'42["auth", {{"session": "{PO_SSID}", "isDemo": 1}}]'
            await ws.send(auth_msg)
            request_msg = f'42["getHistory", {{"asset": "{symbol}", "period": {tf}, "count": {count}}}]'
            await ws.send(request_msg)
            for _ in range(5):
                raw = await ws.recv()
                if "history" in raw:
                    json_str = raw[raw.find('['):]
                    data = json.loads(json_str)
                    candles_raw = data[1].get('history', [])
                    if candles_raw:
                        df = pd.DataFrame(candles_raw)
                        df = df.rename(columns={'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close'})
                        return df[['time', 'open', 'high', 'low', 'close']]
    except Exception as e:
        print(f"PO fetcher error ({symbol}): {e}")
    return None

async def get_otc_candles(symbol, tf="1m", limit=100):
    tf_sec = 60 if tf == "1m" else 300
    df = await get_pocket_option_candles(symbol, tf_sec, limit)
    if df is not None and not df.empty:
        return df
    # Если нет SSID - возвращаем None, а НЕ фейк! Чтобы не слать мусор
    print(f"⚠️ No real data for {symbol}, skip")
    return None

def analyze(df):
    if df is None or len(df) < 50:
        return None

    df['ema9'] = df['close'].ewm(span=9).mean()
    df['ema21'] = df['close'].ewm(span=21).mean()
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    
    # ATR для жирности свечи
    df['tr'] = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    body = abs(last['close'] - last['open'])
    is_fat_candle = body > (last['atr'] * 0.7)  # ЖИРНАЯ свеча

    up_trend = last['ema9'] > last['ema21'] and last['close'] > last['ema9']
    down_trend = last['ema9'] < last['ema21'] and last['close'] < last['ema9']

    bull = last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bear = last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']

    # ТОЛЬКО ЖИРНЫЕ: тренд + поглощение + жирная свеча + RSI в зоне
    if up_trend and bull and is_fat_candle and 45 < last['rsi'] < 68:
        return "CALL 🟢 (ВВЕРХ)", round(last['rsi'], 1)
    if down_trend and bear and is_fat_candle and 32 < last['rsi'] < 55:
        return "PUT 🔴 (ВНИЗ)", round(last['rsi'], 1)

    return None

def send(msg):
    if not BOT_TOKEN or not CHANNEL_ID:
        print(f"[PREVIEW]:\n{msg}\n")
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHANNEL_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

async def main_loop():
    print("🤖 Bot V6 BRODYAGA started...")
    last_signal = {}
    while True:
        hour_utc = datetime.now(timezone.utc).hour
        
        # ПОСЛЕ 19:00 UTC - ТОЛЬКО OTC
        if hour_utc >= 19:
            symbols = OTC
            print(f"🌙 {hour_utc}:00 UTC - Night mode: only OTC")
        else:
            symbols = MAJORS + OTC
            print(f"☀️ {hour_utc}:00 UTC - Day mode: Majors + OTC")

        for sym in symbols:
            try:
                df = await get_otc_candles(sym)
                res = analyze(df)
                if res:
                    # Анти-спам: не шлем по одной паре чаще чем раз в 3 мин
                    now_ts = time.time()
                    if sym in last_signal and now_ts - last_signal[sym] < 180:
                        continue
                    last_signal[sym] = now_ts

                    direction, rsi_val = res
                    t_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
                    clean = sym.replace("_otc", " OTC").upper()
                    
                    send(f"🔥 **BRODYAGA V6 SIGNAL** 🔥\n\n"
                         f"📊 Пара: `{clean}`\n"
                         f"🎯 Направление: **{direction}**\n"
                         f"📈 RSI: `{rsi_val}`\n"
                         f"⏰ Время: `{t_str}`\n"
                         f"⏳ Экспирация: `2-3 мин`")
            except Exception as e:
                print(f"Error {sym}: {e}")
            await asyncio.sleep(1)
        await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main_loop())
