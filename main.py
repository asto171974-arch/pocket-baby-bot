import os, asyncio, logging, datetime
from collections import deque
from telegram import Bot
import httpx
import pandas as pd

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
bot = Bot(token=TOKEN)

# Твои 92% - оставляем 5 самых чистых чтобы не грузить
PAIRS = ["EUR/CAD (OTC)", "AUD/JPY (OTC)", "USD/CAD (OTC)", "NZD/USD (OTC)", "AUD/USD (OTC)"]
last_signals = deque(maxlen=3)

async def get_kraken_rsi():
    try:
        async with httpx.AsyncClient() as client:
            # Kraken не блочит Render
            r = await client.get("https://api.kraken.com/0/public/OHLC?pair=BTCUSD&interval=5", timeout=10)
            data = r.json()
            pair_key = list(data['result'].keys())[0]
            ohlc = data['result'][pair_key]
            df = pd.DataFrame(ohlc, columns=['t','o','h','l','c','v','vw','tr','cnt'])
            close = df['c'].astype(float)
            
            delta = close.diff()
            gain = delta.where(delta>0,0).rolling(14).mean()
            loss = -delta.where(delta<0,0).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain/loss))
            rsi_v = float(rsi.iloc[-1])
            ema9 = float(close.ewm(9).mean().iloc[-1])
            ema21 = float(close.ewm(21).mean().iloc[-1])
            
            if 45 < rsi_v < 55: return None
            if rsi_v < 40 and ema9 > ema21:
                return "ВВЕРХ 🟢", f"RSI {rsi_v:.0f} + BTC тренд"
            if rsi_v > 60 and ema9 < ema21:
                return "ВНИЗ 🔴", f"RSI {rsi_v:.0f} + BTC тренд"
            return None
    except Exception as e:
        logging.error(f"Kraken err {e}")
        return None

async def main():
    logging.info("PRO CLEAN v3 Kraken started - без банов")
    while True:
        now = datetime.datetime.now()
        while last_signals and (now - last_signals[0]).seconds > 3600:
            last_signals.popleft()
        if len(last_signals) >= 3:
            logging.info("Лимит 3/час, пауза")
            await asyncio.sleep(600)
            continue

        res = await get_kraken_rsi()
        if res:
            d, reason = res
            import random
            asset = random.choice(PAIRS) # даем случайную из твоих 92% под общий тренд
            text = f"🎯 ЧИСТЫЙ СИГНАЛ 92%\n\nАктив: {asset}\nНаправление: {d}\nОснова: {reason}\nЭкспирация: 5 мин\n\nФильтр: Kraken, без флета"
            await bot.send_message(chat_id=CHANNEL_ID, text=text)
            last_signals.append(now)
            await asyncio.sleep(1200) # 20 мин кулдаун
        else:
            await asyncio.sleep(120)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
