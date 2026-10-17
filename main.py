import os, asyncio, logging, random
from datetime import datetime
from telegram import Bot

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Pocket_baby_bot")
bot = Bot(token=BOT_TOKEN)

async def send_signal():
    pair = random.choice(["EUR/USD","GBP/USD","USD/JPY"])
    direction = random.choice(["ВВЕРХ 🟢","ВНИЗ 🔴"])
    text = f"🚀 СИГНАЛ\nПара: {pair}\nНапр: {direction}\nВремя: {datetime.now().strftime('%H:%M:%S')}"
    await bot.send_message(chat_id=CHANNEL_ID, text=text)

async def main_loop():
    await send_signal()
    while True:
        await asyncio.sleep(300)
        await send_signal()

if __name__ == "__main__":
    asyncio.run(main_loop())
