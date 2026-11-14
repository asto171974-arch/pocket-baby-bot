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
        self.wfile.write(b"Brodyaga v3.1 OTC History running")
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

# ==================== ЛОКАЛЬНЫЙ БЭКТЕСТ ПО СНИМКУ ОТС ====================
def analyze_otc_screenshot(photo_path):
    img = cv2.imread(photo_path)
    if img is None:
        return None, 0, 0, 0
    h, w = img.shape[:2]
    chart = img[int(h*0.18):int(h*0.65), 0:int(w*0.95)]
    if chart.size == 0:
        return None, 0, 0, 0

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

    if len(prices) < 60:
        return None, 0, 0, 0

    prices = prices[::-1]
    rsi_series = calc_rsi(prices)
    curr_rsi = rsi_series.iloc[-1]
    curr_price = prices[-1]
    ema21 = pd.Series(prices).ewm(span=21).mean()

    # Защита от частого спама (кулдаун 2 минуты)
    if time.time() - sniper_state["last_signal_time"] < 120:
        return "СТОП, ПОДОЖДИ 2 МИН ПОСЛЕ СИГНАЛА", curr_rsi, 0, 0

    # Проводим локальный бэктест по историческим свечам на скриншоте
    similar = 0
    wins_up = 0
    wins_down = 0

    for i in range(25, len(prices) - 5):
        if pd.isna(rsi_series.iloc[i]):
            continue
        # Ищем похожие точки по RSI и положению относительно EMA
        if abs(rsi_series.iloc[i] - curr_rsi) < 3.0 and (prices[i] > ema21.iloc[i]) == (curr_price > ema21.iloc[-1]):
            similar += 1
            future_diff = prices[i + 3] - prices[i]
            if future_diff > 0:
                wins_up += 1
            else:
                wins_down += 1

    if similar < 5:
        return None, curr_rsi, 0, similar

    win_rate = max(wins_up, wins_down) / similar * 100
    
    # Требуем точность от 75% на видимой истории скриншота
    if win_rate < 75:
        return None, curr_rsi, win_rate, similar

    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return direction, curr_rsi, win_rate, similar

async def send_text(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                     json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

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
    print("Бот слушает с историческим анализом OTC...")
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
                        await send_text(chat_id, "Привет!\n1. Напиши пару (например `EUR/USD`) — бот проверит реал.\n2. Напиши `OTC` — бот попросит скриншот и проведет исторический бэктест.")
                    elif text == "/stop":
                        sniper_state["waiting_photo"] = False
                        await send_text(chat_id, "Остановлен")
                    elif text in MAJORS:
                        await send_text(chat_id, f"Проверяю {text} по реальным свечам...")
                        asyncio.create_task(check_major_signal(text, chat_id))
                    elif text.upper() == "OTC":
                        sniper_state["waiting_photo"] = True
                        sniper_state["chat_id"] = chat_id
                        await send_text(chat_id, "📷 Кидай скриншот OTC-графика (1м), я посчитаю историю и винрейт.")

                    if "photo" in msg and sniper_state["waiting_photo"]:
                        file_id = msg["photo"][-1]["file_id"]
                        file_res = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file_id})
                        file_path = file_res.json()["result"]["file_path"]
                        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                        photo_data = await client.get(photo_url)
                        open("/tmp/screen.jpg", "wb").write(photo_data.content)

                        direction, rsi, wr, similar = analyze_otc_screenshot("/tmp/screen.jpg")
                        
                        if direction and "СТОП" in direction:
                            await send_text(chat_id, direction)
                        elif direction:
                            await send_text(chat_id, f"🔥 **OTC СНАЙПЕРСКИЙ СИГНАЛ**\n\nНаправление: **{direction}**\nRSI: `{rsi:.1f}`\nИсторический Винрейт: **{wr:.0f}%**\nСовпадений в истории скриншота: `{similar}`\nЭкспирация: `2-3 мин`\n⚠️ *Только демо-счет*")
                            sniper_state["last_signal_time"] = time.time()
                        else:
                            await send_text(chat_id, f"💤 ЖДИ. Нет сильного сетапа (винрейт ниже 75%).\nRSI: `{rsi:.1f}`, похожих точек: `{similar}`")
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
