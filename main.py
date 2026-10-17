import os, asyncio, logging, threading
from telegram import Bot
from flask import Flask

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Pocket_baby_bot")
bot = Bot(token=BOT_TOKEN)

app = Flask(__name__)
@app.route('/')
def home(): return "Brodyaga is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def send_signal():
    from random import choice
    pair = choice(["EUR/USD","GBP/USD","BTC/USD"])
    direction = choice(["ВВЕРХ 🟢","ВНИЗ 🔴"])
    text = f"🚀 СИГНАЛ от Бродяги\nПара: {pair}\nНаправление: {direction}"
    await bot.send_message(chat_id=CHANNEL_ID, text=text)

async def main_loop():
    while True:
        try:
            await send_signal()
        except Exception as e:
            logging.error(e)
        await asyncio.sleep(300)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(main_loop())
