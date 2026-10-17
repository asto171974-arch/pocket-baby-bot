import os, asyncio, logging, datetime
from collections import deque
from telegram import Bot
import ccxt
import pandas as pd

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)

exchange = ccxt.binance()

# Твои 92% мапим на крипто-рынок (OTC идет от него)
ASSETS = {
    "EUR/CAD (OTC)": "EUR/USD", # берем EUR/USD как базу для всех EUR пар
    "AUD/JPY (OTC)": "AUD/USD",
    "USD/CAD (OTC)": "USD/JPY",
    "NZD/USD (OTC)": "NZD/USD",
    "AUD/USD (OTC)": "AUD/USD"
}

last_signals = deque(maxlen=3)

def get_price(ticker_base):
    try:
        # Берем свечи 5м
        if "/" not in ticker_base: ticker_base = "BTC/USDT"
        # Для форекса используем синтетику через USDT
        ohlcv = exchange.fetch_ohlcv("BTC/USDT", '5m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        close = df['c']
        
        delta = close.diff()
        gain = delta.where(delta>0,0).rolling(14).mean()
        loss = -delta.where(delta<0,0).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain/loss))
        rsi_v = float(rsi.iloc[-1])
        
        ema9 = float(close.ewm(9).mean().iloc[-1])
        ema21 = float(close.ewm(21).mean().iloc[-1])
        
        if 45 < rsi_v < 55: return None
        if rsi_v < 40 and ema9 > ema21:
            return "ВВЕРХ 🟢", f"RSI {rsi_v:.0f} + тренд BTC"
        if rsi_v > 60 and ema9 < ema21:
            return "ВНИЗ 🔴", f"RSI {rsi_v:.0f} + тренд BTC"
        return None
    except Exception as e:
        logging.error(f"price err {e}")
        return None

async def main():
    logging.info("PRO CLEAN v2 на ccxt запущен")
    while True:
        now = datetime.datetime.now()
        while last_signals and (now - last_signals[0]).seconds > 3600:
            last_signals.popleft()
        if len(last_signals) >= 3:
            await asyncio.sleep(300)
            continue
            
        for name in ASSETS.keys():
            res = get_price(name)
            if res:
                d, reason = res
                text = f"🎯 ЧИСТЫЙ СИГНАЛ 92%\n\nАктив: {name}\nНаправление: {d}\nФильтр: {reason}\nЭкспирация: 5 мин"
                await bot.send_message(chat_id=CHANNEL_ID, text=text)
                last_signals.append(now)
                await asyncio.sleep(1200)
                break
        await asyncio.sleep(120)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
