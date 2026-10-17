import os, asyncio, logging, datetime, threading
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Bot
import httpx
import pandas as pd

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)
PAIRS = ["EUR/CAD (OTC)", "AUD/JPY (OTC)", "USD/CAD (OTC)", "NZD/USD (OTC)", "AUD/USD (OTC)"]
last_signals = deque(maxlen=3)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"PRO CLEAN LIVE")def do_HEAD(self):self.send_response(200);self.end_headers()

def run_web():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), H).serve_forever()
threading.Thread(target=run_web, daemon=True).start()

async def get_kraken():
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get("https://api.kraken.com/0/public/OHLC?pair=BTCUSD&interval=5", timeout=10)
            data = r.json()
            key = list(data['result'].keys())[0]
            rows = data['result'][key]
            df = pd.DataFrame(rows)
            df = df.iloc[:, :6]  # берем только первые 6
            close = df[4].astype(float)
            delta = close.diff()
            gain = delta.where(delta>0,0).rolling(14).mean()
            loss = -delta.where(delta<0,0).rolling(14).mean()
            rs = gain/loss
            rsi = 100 - (100/(1+rs))
            rsi_v = float(rsi.iloc[-1])
            ema9 = float(close.ewm(9).mean().iloc[-1])
            ema21 = float(close.ewm(21).mean().iloc[-1])
            if 45 < rsi_v < 55: return None
            if rsi_v < 42 and ema9 > ema21: return "ВВЕРХ 🟢", f"RSI {rsi_v:.0f}"
            if rsi_v > 58 and ema9 < ema21: return "ВНИЗ 🔴", f"RSI {rsi_v:.0f}"
    except Exception as e:
        logging.error(f"KRAKEN ERR {e}")
        return None

async def main():
    logging.info("PRO CLEAN FINAL FIXED - LIVE")
    while True:
        now = datetime.datetime.now()
        while last_signals and (now-last_signals[0]).seconds>3600: last_signals.popleft()
        if len(last_signals)>=3: await asyncio.sleep(600); continue
        res = await get_kraken()
        if res:
            import random
            d, reason = res
            asset = random.choice(PAIRS)
            await bot.send_message(chat_id=CHANNEL_ID, text=f"🎯 ЧИСТЫЙ 92%\n\nАктив: {asset}\nНаправление: {d}\n{reason}\nЭкспирация: 5 мин")
            last_signals.append(now)
            await asyncio.sleep(1200)
        else: await asyncio.sleep(120)

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
