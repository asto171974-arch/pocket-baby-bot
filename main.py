import os
import time
import asyncio
import cv2
import pandas as pd
import numpy as np
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga v3.3 OTC Expiration 1-2m running")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "AUD/USD"]

sniper_state = {"waiting_photo": False, "chat_id": None, "last_signal_time": 0}

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_real_candles(pair):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=1000&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r:
            return None
        return [float(x['close']) for x in reversed(r['values'])]
    except:
        return None

def is_market_open():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if now.weekday() in [5, 6]: # Суббота, Воскресенье
        return False
    if now.weekday() == 0 and now.hour < 3:
        return False
    return True

# ==================== АНАЛИЗ ИСТОЩЕНИЯ ИМПУЛЬСА (OTC) ====================
def analyze_otc_screenshot(photo_path):
    img = cv2.imread(photo_path)
    if img is None:
        return None, 0, 0
    h, w = img.shape[:2]
    chart = img[int(h*0.18):int(h*0.65), 0:int(w*0.95)]
    if chart.size == 0:
        return None, 0, 0

    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red_mask1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red_mask2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    candles_mask = cv2.bitwise_or(green_mask, cv2.bitwise_or(red_mask1, red_mask2))

    prices = []
    for x in range(candles_mask.shape[1]-5, 0, -2):
        col = np.where(candles_mask[:, x] > 0)[0]
        if len(col) > 0:
            prices.append(chart.shape[0] - col.mean())

    if len(prices) < 30:
        return None, 0, 0

    prices = prices[::-1]

    # Кулдаун 2 минуты между сигналами
    if time.time() - sniper_state["last_signal_time"] < 120:
        return "СТОП, ПОДОЖДИ 2 МИН ПОСЛЕ СИГНАЛА", 0, 0

    deltas = np.diff(prices)
    if len(deltas) < 6:
        return None, 0, 0

    recent_deltas = deltas[-5:]
    signal = None

    # Логика истощения движения (вход против локального дожима)
    if all(d > 0 for d in recent_deltas[-4:-1]) and recent_deltas[-1] < recent_deltas[-2] * 0.5:
        signal = "ВНИЗ 🔴 (Истощение роста)"
    elif all(d < 0 for d in recent_deltas[-4:-1]) and abs(recent_deltas[-1]) < abs(recent_deltas[-2]) * 0.5:
        signal = "ВВЕРХ 🟢 (Истощение падения)"

    if not signal:
        return None, 0, 0

    return signal, 85, len(prices)

async def send_text(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

# ==================== МАЖОРЫ (РЕАЛ TWELVE DATA) ====================
async def check_major_signal(pair, chat_id):
    if not is_market_open():
        await send_text(chat_id, "Реал закрыт до понедельника. Пиши OTC и кидай скрин.")
        return
    prices = get_real_candles(pair)
    if not prices or len(prices) < 300:
        await send_text(chat_id, "Не смог взять свечи. Проверь TWELVEDATA_API_KEY")
        return
    rsi = calc_rsi(prices)
    ema200 = pd.Series(prices).ewm(span=200).mean()
    curr_rsi = rsi.iloc[-1]
    wins = 0
    total = 0
    for i in range(200, len(prices)-5):
        if rsi.iloc[i] <= 30 and prices[i] < ema200.iloc[i]:
            total += 1
            if prices[i+3] > prices[i]:
                wins += 1
        elif rsi.iloc[i] >= 70 and prices[i] > ema200.iloc[i]:
            total += 1
            if prices[i+3] < prices[i]:
                wins += 1
    if total < 20:
        await send_text(chat_id, f"{pair}: мало статистики ({total}), жди")
        return
    wr = wins/total*100
    if wr < 58:
        await send_text(chat_id, f"{pair}: винрейт {wr:.0f}% - слабый, не захожу")
        return
    direction = "ВВЕРХ" if curr_rsi <= 30 else "ВНИЗ"
    await send_text(chat_id, f"МАЖОР {pair}\nRSI: {curr_rsi:.1f}\n{direction}\nВинрейт: {wr:.0f}% на {total} сделках\nЭкспирация 3м")

async def telegram_listener():
    offset = 0
    print("Бот запущен с экспирацией 1-2м для OTC...")
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                                     params={"offset": offset, "timeout": 25})
                data = r.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    if not chat_id:
                        continue
                    text = msg.get("text", "").strip()

                    if text == "/start":
                        await send_text(chat_id, "Привет!\n1. Напиши пару (например `EUR/USD`) — бот проверит реал.\n2. Напиши `OTC` — бот попросит скриншот (экспирация 1-2 мин).")
                    elif text == "/stop":
                        sniper_state["waiting_photo"] = False
                        await send_text(chat_id, "Остановлен")
                    elif text in MAJORS:
                        await send_text(chat_id, f"Проверяю {text} по реальным свечам...")
                        asyncio.create_task(check_major_signal(text, chat_id))
                    elif text.upper() == "OTC":
                        sniper_state["waiting_photo"] = True
                        sniper_state["chat_id"] = chat_id
                        await send_text(chat_id, "📷 Кидай скриншот OTC-графика (1м). Жду истощение импульса для входа на 1-2 минуты.")

                    if "photo" in msg and sniper_state["waiting_photo"]:
                        file_id = msg["photo"][-1]["file_id"]
                        file_res = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file_id})
                        file_path = file_res.json()["result"]["file_path"]
                        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                        photo_data = await client.get(photo_url)
                        open("/tmp/screen.jpg", "wb").write(photo_data.content)

                        direction, confidence, count = analyze_otc_screenshot("/tmp/screen.jpg")
                        
                        if direction and "СТОП" in direction:
                            await send_text(chat_id, direction)
                        elif direction:
                            await send_text(chat_id, f"🔥 **OTC СНАЙПЕР (ИСТОЩЕНИЕ)**\n\nСигнал: **{direction}**\nТочек анализа: `{count}`\n⏱ **Экспирация: 1–2 мин**\n⚠️ *Торговля против дожима маркет-мейкера*")
                            sniper_state["last_signal_time"] = time.time()
                        else:
                            await send_text(chat_id, f"💤 ЖДИ. Импульс сильный, истощения нет. Ждем разворотную точку.")
                        sniper_state["waiting_photo"] = False
            except Exception as e:
                print("Ошибка:", e)
                await asyncio.sleep(3)

async def sniper_loop():
    while True:
        await asyncio.sleep(60)

async def main():
    await asyncio.gather(telegram_listener(), sniper_loop())

if __name__ == "__main__":
    asyncio.run(main())
