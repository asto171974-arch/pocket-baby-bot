import os, asyncio, logging, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Bot
import yfinance as yf

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)

# === ФИКС ДЛЯ RENDER - ОТКРЫВАЕМ ПОРТ ===
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

def run_web():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()
# === КОНЕЦ ФИКСА ===

ASSETS = {
    "TOYOTA (OTC)": "TM",
    "VISA (OTC)": "V",
    "EUR/CAD (OTC)": "EURCAD=X",
    "AUD/JPY (OTC)": "AUDJPY=X",
    "USD/CAD (OTC)": "USDCAD=X",
    "USD/CNH (OTC)": "USDCNH=X",
    "AUD/CHF (OTC)": "AUDCHF=X",
    "NZD/USD (OTC)": "NZDUSD=X",
    "AUD/USD (OTC)": "AUDUSD=X",
    "CAD/JPY (OTC)": "CADJPY=X",
    "EUR/AUD (OTC)": "EURAUD=X",
    "GBP/CHF (OTC)": "GBPCHF=X"
}

def analyze(ticker):
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        if len(df) < 35: return None
        close = df['Close']
        delta = close.diff()
        gain = delta.where(delta>0,0).rolling(14).mean()
        loss = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        rsi_v = float(rsi.iloc[-1])
        if 45 < rsi_v < 55: return None
        ema9 = float(close.ewm(9).mean().iloc[-1])
        ema21 = float(close.ewm(21).mean().iloc[-1])
        return ("ВВЕРХ 🟢", f"RSI {rsi_v:.0f}") if rsi_v < 40 and ema9 > ema21 else ("ВНИЗ 🔴", f"RSI {rsi_v:.0f}") if rsi_v > 60 and ema9 < ema21 else None
    except: return None

async def main():
    logging.info("Bot PRO CLEAN started")
    while True:
        for name, ticker in ASSETS.items():
            res = analyze(ticker)
            if res:
                d, r = res
                await bot.send_message(chat_id=CHANNEL_ID, text=f"🎯 {name}\n{d}\n{r}\nВыплата 92%")
                await asyncio.sleep(1200)
                break
        await asyncio.sleep(120)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
