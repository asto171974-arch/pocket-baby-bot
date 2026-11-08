import os
import time
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

MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY", "AUDUSD"]
OTC = ["EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "EURJPY_otc", "AUDUSD_otc", "NZDUSD_otc", "GBPJPY_otc", "EURGBP_otc", "AUDCAD_otc"]

async def get_pocket_option_candles(symbol="EURUSD_otc", tf=60, count=100):
    if not PO_SSID:
        print("❌ NO SSID")
        return None
    try:
        async with websockets.connect(PO_WS_URL, ping_interval=20) as ws:
            # 1. Ждём open пакет 0{...}
            await asyncio.wait_for(ws.recv(), timeout=10)
            # 2. Подключаемся к namespace
            await ws.send('40')
            await asyncio.wait_for(ws.recv(), timeout=10)
            # 3. Авторизация
            auth_msg = f'42["auth",{{"session":"{PO_SSID}","isDemo":true,"uid":0,"platform":2}}]'
            await ws.send(auth_msg)
            await asyncio.sleep(1)
            # 4. Запрос истории
            request_msg = f'42["getHistory",{{"asset":"{symbol}","period":{tf},"count":{count}}}]'
            await ws.send(request_msg)
            
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                if 'history' in raw:
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

async def get_otc_candles(symbol):
    df = await get_pocket_option_candles(symbol, 60, 100)
    if df is not None and not df.empty:
        return df
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
    last = df.iloc[-1]
    prev = df.iloc[-2]
    up_trend = last['ema9'] > last['ema21']
    down_trend = last['ema9'] < last['ema21']
    bull = last['close'] > last['open'] and last['close'] > prev['high']
    bear = last['close'] < last['open'] and last['close'] < prev['low']
    # ОСЛАБИЛИ: без жирной свечи, шире RSI
    if up_trend and bull and 40 < last['rsi'] < 75:
        return "CALL 🟢 (ВВЕРХ)", round(last['rsi'], 1)
    if down_trend and bear and 25 < last['rsi'] < 60:
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
        symbols = OTC if hour_utc >= 19 else MAJORS + OTC
        print(f"🕒 {hour_utc}:00 UTC check {len(symbols)} pairs")
        for sym in symbols:
            try:
                df = await get_otc_candles(sym)
                res = analyze(df)
                if res:
                    now_ts = time.time()
                    if sym in last_signal and now_ts - last_signal[sym] < 180:
                        continue
                    last_signal[sym] = now_ts
                    direction, rsi_val = res
                    t_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
                    clean = sym.replace("_otc", " OTC").upper()
                    send(f"🔥 **BRODYAGA V6 SIGNAL** 🔥\n\n📊 Пара: `{clean}`\n🎯 Направление: **{direction}**\n📈 RSI: `{rsi_val}`\n⏰ Время: `{t_str}`\n⏳ Экспирация: `2-3 мин`")
                    print(f"✅ SIGNAL {sym} {direction}")
            except Exception as e:
                print(f"Error {sym}: {e}")
            await asyncio.sleep(1)
        await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(main_loop())
