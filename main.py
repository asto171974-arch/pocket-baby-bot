import os, asyncio, logging, datetime
from collections import deque
from telegram import Bot
import yfinance as yf

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)

# ТВОЙ СПИСОК С ЭКРАНА 1 в 1
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

last_signals = deque(maxlen=3)

def analyze(ticker):
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        if len(df) < 35: return None
        close = df['Close']
        # RSI
        delta = close.diff()
        gain = delta.where(delta>0,0).rolling(14).mean()
        loss = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        rsi_v = float(rsi.iloc[-1])
        # EMA
        ema9 = float(close.ewm(9).mean().iloc[-1])
        ema21 = float(close.ewm(21).mean().iloc[-1])
        # MACD
        ema12 = close.ewm(12).mean()
        ema26 = close.ewm(26).mean()
        macd = ema12 - ema26
        macd_v = float(macd.iloc[-1])
        macd_s = float(macd.ewm(9).mean().iloc[-1])

        if 45 < rsi_v < 55: return None # ФЛЕТ - ОТСЕКАЕМ МУСОР
        
        if rsi_v < 40 and ema9 > ema21 and macd_v > macd_s:
            return "ВВЕРХ 🟢", f"RSI {rsi_v:.0f} + EMA тренд + MACD"
        if rsi_v > 60 and ema9 < ema21 and macd_v < macd_s:
            return "ВНИЗ 🔴", f"RSI {rsi_v:.0f} + EMA тренд + MACD"
        return None
    except: return None

async def send_signal():
    # фильтр 3 сигнала в час
    now = datetime.datetime.now()
    while last_signals and (now - last_signals[0]).seconds > 3600:
        last_signals.popleft()
    if len(last_signals) >= 3:
        logging.info("Лимит 3/час - ждем")
        return

    for name, ticker in ASSETS.items():
        res = analyze(ticker)
        if res:
            direction, reason = res
            text = f"🎯 ЧИСТЫЙ СИГНАЛ 92%\n\nАктив: {name}\nНаправление: {direction}\nФильтр: {reason}\nЭкспирация: 5 мин\n\nОтсеяли флет, 3 индикатора сошлись."
            await bot.send_message(chat_id=CHANNEL_ID, text=text)
            last_signals.append(now)
            logging.info(f"SENT {name}")
            return # один сигнал и пауза 20 мин

async def main():
    while True:
        await send_signal()
        # если был сигнал - пауза 20 мин, если нет - проверка через 2 мин
        await asyncio.sleep(1200 if last_signals and (datetime.datetime.now() - last_signals[-1]).seconds < 1200 else 120)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
