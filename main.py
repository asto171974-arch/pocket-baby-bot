import os, asyncio, json
import pandas as pd
import httpx
import websockets
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V5 REAL OTC running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()

Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
B_URL = os.getenv("BINARIUM_WS_URL")
B_TOKEN = os.getenv("BINARIUM_TOKEN")

async def get_real_candles_B(symbol="EUR/USD OTC", tf="1m", count=100):
    headers = {"Authorization": f"Bearer {B_TOKEN}"}
    payload = {"action": "get_candles", "symbol": symbol, "timeframe": tf, "count": count}
    try:
        async with websockets.connect(B_URL, extra_headers=headers) as ws:
            await ws.send(json.dumps(payload))
            raw = await ws.recv()
            data = json.loads(raw)
            candles = data.get('candles') or data.get('data') or []
            df = pd.DataFrame(candles)
            if df.empty: return None
            if len(df.columns) >= 5:
                df.columns = ['time','open','high','low','close'][:len(df.columns)]
            return df
    except Exception as e:
        print(f"fetch err: {e}")
        return None

def analyze(df):
    if df is None or len(df) < 50: return None
    df = df.copy()
    df['ema9'] = df['close'].ewm(span=9).mean()
    df['ema21'] = df['close'].ewm(span=21).mean()
    df['rsi'] = 100 - (100 / (1 + df['close'].diff().clip(lower=0).rolling(14).mean() / (-df['close'].diff().clip(upper=0).rolling(14).mean().abs() + 1e-9)))
    last = df.iloc[-1]
    prev = df.iloc[-2]
    up = last['ema9'] > last['ema21'] and last['close'] > last['ema9']
    down = last['ema9'] < last['ema21'] and last['close'] < last['ema9']
    bull = last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bear = last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']
    if up and last['rsi'] < 70 and bull: return "CALL", round(last['rsi'],1)
    if down and last['rsi'] > 30 and bear: return "PUT", round(last['rsi'],1)
    return None

SYMBOLS = ["EUR/USD OTC","GBP/USD OTC","USD/JPY OTC","EUR/JPY OTC","AUD/USD OTC"]

def format_signal(sym, direction, rsi_val, tf="1m"):
    t = datetime.now().strftime("%H:%M:%S")
    return f"V5 SIGNAL {sym}\nDir: {direction}\nTF: {tf}\nRSI: {rsi_val}\nTime: {t}"

async def main_loop():
    async with httpx.AsyncClient() as client:
        while True:
            for sym in SYMBOLS:
                df = await get_real_candles_B(sym)
                res = analyze(df)
                if res:
                    d, r = res
                    txt = format_signal(sym, d, r)
                    try:
                        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHANNEL_ID, "text": txt})
                    except Exception as e:
                        print(e)
                await asyncio.sleep(1)
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main_loop())
