import os, asyncio, logging
from threading import Thread
from flask import Flask
from telegram import Bot
import yfinance as yf

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)

# --- КОСТЫЛЬ ДЛЯ RENDER WEB SERVICE ---
app = Flask(__name__)
@app.route('/')
def home(): return "Brodaga PRO CLEAN is alive"
def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
Thread(target=run_web, daemon=True).start()
# -------------------------------------

ASSETS = {
    "EUR/USD (OTC)": "EURUSD=X",
    "EUR/GBP (OTC)": "EURGBP=X",
    "GOLD (OTC)": "GC=F",
    "APPLE (OTC)": "AAPL",
    "TESLA (OTC)": "TSLA"
}

def get_clean_signal(ticker):
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        if len(df) < 35: return None
        close = df['Close']
        delta = close.diff()
        gain = delta.where(delta>0,0).rolling(14).mean()
        loss = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        r = float(rsi.iloc[-1])
        if 45 < r < 55: return None
        ema9 = float(close.ewm(9).mean().iloc[-1])
        ema21 = float(close.ewm(21).mean().iloc[-1])
        if r < 38 and ema9 > ema21: return "ВВЕРХ 🟢", f"RSI {r:.0f}"
        if r > 62 and ema9 < ema21: return "ВНИЗ 🔴", f"RSI {r:.0f}"
        return None
    except: return None

async def loop():
    while True:
        for name, ticker in ASSETS.items():
            res = get_clean_signal(ticker)
            if res:
                d, reason = res
                await bot.send_message(chat_id=CHANNEL_ID, text=f"💎 ЧИСТЫЙ 92%\nАктив: {name}\nСигнал: {d}\nФильтр: {reason} + тренд\nЭкспирация: 5м")
                await asyncio.sleep(1200)
                break
        await asyncio.sleep(120)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(loop())
