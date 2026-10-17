import os, asyncio, logging, threading, datetime
from telegram import Bot
from flask import Flask
from random import choice

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
    # Проверяем день недели
    weekday = datetime.datetime.now().weekday() # 0-4 будни, 5-6 вых

    if weekday >= 5:
        # СУББОТА-ВОСКРЕСЕНЬЕ: только то что работает
        pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "EUR/USD OTC", "GBP/USD OTC", "USD/JPY OTC", "AUD/USD OTC"]
        mode = "WEEKEND (Crypto + OTC)"
    else:
        # БУДНИ: форекс + крипта
        pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "BTC/USD", "ETH/USD"]
        mode = "WEEKDAY"

    pair = choice(pairs)
    direction = choice(["ВВЕРХ 🟢", "ВНИЗ 🔴"])
    
    text = f"🚀 СИГНАЛ от Бродяги\nПара: {pair}\nНаправление: {direction}\nВремя: {datetime.datetime.now().strftime('%H:%M')} МСК\nРежим: {mode}\nЭкспирация: 5 мин"
    
    await bot.send_message(chat_id=CHANNEL_ID, text=text)
    logging.info(f"Sent {pair} {direction}")

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
