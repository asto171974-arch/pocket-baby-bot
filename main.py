import os
import asyncio
import pandas as pd
import httpx
import cv2
import numpy as np
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==================== СЕРВЕР ДЛЯ RENDER ====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga Bot v3 running")
    def log_message(self, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

Thread(target=run_server, daemon=True).start()

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "AUD/USD"]
OTC_PAIRS = ["EUR/USD-OTC", "GBP/USD-OTC", "USD/JPY-OTC"]

sniper_state = {
    "active": False,
    "target_pair": None,
    "chat_id": None,
    "last_win_time": 0
}

# ==================== ИНДИКАТОРЫ ====================
def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_real_candles(pair):
    if not TWELVE_KEY:
        return None
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=1000&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r:
            print(f"API Error {pair}: {r}")
            return None
        return [float(x['close']) for x in reversed(r['values'])]
    except Exception as e:
        print(f"Candle error: {e}")
        return None

# ==================== АНАЛИЗ СКРИНА OTC (EMA 50) ====================
def analyze_otc_screenshot(photo_path):
    img = cv2.imread(photo_path)
    if img is None:
        return None, 0, "Не смог открыть скрин"

    # Координаты с ТВОЕГО скрина EUR/USD OTC
    h, w = img.shape[:2]
    # График примерно 15% сверху до 75% снизу
    chart = img[int(h*0.12):int(h*0.72), int(w*0.0):int(w*0.68)]
    if chart.size == 0:
        chart = img

    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)

    # Зелёные и красные свечи
    green_mask = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red_mask1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red_mask2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    candles_mask = cv2.bitwise_or(green_mask, cv2.bitwise_or(red_mask1, red_mask2))

    # Голубая EMA 50
    blue_mask = cv2.inRange(hsv, np.array([80,80,80]), np.array([105,255,255]))

    prices = []
    emas = []
    for x in range(candles_mask.shape[1]-5, 0, -2):
        col = np.where(candles_mask[:, x] > 0)[0]
        ecol = np.where(blue_mask[:, x] > 0)[0]
        if len(col) > 0:
            prices.append(chart.shape[0] - col.mean())
        if len(ecol) > 0:
            emas.append(chart.shape[0] - ecol.mean())

    if len(prices) < 50:
        return None, 0, "Не вижу свечи. Кидай скрин целиком, не обрезанный"

    prices = prices[::-1]
    curr_price = prices[-1]
    curr_ema = emas[0] if emas else pd.Series(prices).ewm(span=50).mean().iloc[-1]
    rsi = calc_rsi(prices).iloc[-1]

    # ТВОЯ СТРАТЕГИЯ: ловля дна/потолка после импульса 150+ пунктов
    # Приблизительно считаем импульс по разнице max-min последних 50 свечей
    impulse = max(prices[-50:]) - min(prices[-50:])

    # ЗАЩИТА ОТ РЕВАНША
    if asyncio.get_event_loop().time() - sniper_state["last_win_time"] < 60:
        return None, rsi, "СТОП. Ты только выиграл. Жди 5 минут, не реваншируйся"

    # ВВЕРХ: было падение, пробили EMA50 вверх
    if curr_price > curr_ema and impulse > 30 and rsi < 55:
        sniper_state["last_win_time"] = asyncio.get_event_loop().time()
        return "ВВЕРХ 🟢", rsi, f"Пробил EMA50 вверх. RSI {rsi:.0f}"

    # ВНИЗ: было рост, пробили EMA50 вниз
    if curr_price < curr_ema and impulse > 30 and rsi > 45:
        sniper_state["last_win_time"] = asyncio.get_event_loop().time()
        return "ВНИЗ 🔴", rsi, f"Пробил EMA50 вниз. RSI {rsi:.0f}"

    # ЗАПРЕТ ПРОДАВАТЬ В РОСТ
    if curr_price > curr_ema and prices[-1] > prices[-3]:
        return None, rsi, f"НЕ ПРОДАВАТЬ. Цена над EMA50, тренд вверх. RSI {rsi:.0f}. Жди отката"

    return None, rsi, f"Нет сетапа. Цена у EMA50. RSI {rsi:.0f}. Жди следующую свечу 1м"

# ==================== TELEGRAM ====================
async def send_text(chat_id, text):
    if not BOT_TOKEN: return
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10
        )

async def send_menu(chat_id):
    keyboard = []
    row = []
    for pair in MAJORS:
        row.append({"text": f"📈 {pair}", "callback_data": f"scan_{pair}"})
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)

    keyboard.append([{"text": "--- 🌙 OTC (по скрину) ---", "callback_data": "ignore"}])

    row = []
    for pair in OTC_PAIRS:
        row.append({"text": f"🔥 {pair}", "callback_data": f"scan_{pair}"})
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)

    keyboard.append([
        {"text": "🛑 Стоп", "callback_data": "stop_sniper"},
        {"text": "📊 Статус", "callback_data": "status_sniper"}
    ])

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "🎯 <b>БРОДЯГА БОТ v3</b>\n\nМажоры - беру реал.\nOTC - кидай скрин 1м, я посмотрю EMA50.\nЧестно: 85% не будет, будет 55-65% если не тильтуешь.",
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": keyboard}
            },
            timeout=10
        )

async def telegram_listener():
    offset = 0
    print("Telegram Listener запущен...")
    while True:
        try:
            if not BOT_TOKEN:
                await asyncio.sleep(5); continue

            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            async with httpx.AsyncClient() as client:
                data = (await client.get(url, timeout=35)).json()

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        q = update["callback_query"]
                        chat_id = q["message"]["chat"]["id"]
                        async with httpx.AsyncClient() as client:
                            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": q["id"]})

                        data_val = q["data"]
                        if data_val.startswith("scan_"):
                            pair = data_val.replace("scan_", "")
                            sniper_state["target_pair"] = pair
                            sniper_state["active"] = True
                            sniper_state["chat_id"] = chat_id
                            if "OTC" in pair:
                                await send_text(chat_id, f"🔥 <b>{pair}</b> выбран.\n\nТеперь открой график 1м на Покете и <b>кидай сюда скрин</b>. Я посмотрю EMA50.")
                            else:
                                await send_text(chat_id, f"🎯 Снайпер на <b>{pair}</b> (реал). Ищу сетап...")

                        elif data_val == "stop_sniper":
                            sniper_state["active"] = False
                            await send_text(chat_id, "🛑 Остановлен")
                        elif data_val == "status_sniper":
                            status = "Активен 🟢" if sniper_state["active"] else "Спит 💤"
                            await send_text(chat_id, f"📊 {status}\nЦель: {sniper_state['target_pair'] or 'нет'}")

                    elif "message" in update:
                        msg = update["message"]
                        chat_id = msg.get("chat", {}).get("id")
                        text = msg.get("text", "").strip()

                        if text.startswith("/start") or text.startswith("/menu"):
                            await send_menu(chat_id)

                        # ОБРАБОТКА СКРИНА OTC
                        if "photo" in msg:
                            file_id = msg["photo"][-1]["file_id"]
                            async with httpx.AsyncClient() as client:
                                file_data = (await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")).json()
                                file_path = file_data["result"]["file_path"]
                                img_bytes = (await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")).content
                            open("/tmp/screen.jpg", "wb").write(img_bytes)

                            direction, rsi, reason = analyze_otc_screenshot("/tmp/screen.jpg")
                            if direction:
                                await send_text(chat_id, f"💎 <b>СИГНАЛ ПО СКРИНУ</b>\n\n{direction}\nRSI: {rsi:.0f}\n{reason}\n⏳ Экспирация: 2 МИН\nСумма: не больше 2% банка!")
                            else:
                                await send_text(chat_id, f"⏳ <b>ЖДИ</b>\n{reason}")

        except Exception as e:
            print(f"Listener error: {e}")
            await asyncio.sleep(5)
        await asyncio.sleep(1)

# ==================== ЦИКЛ ДЛЯ МАЖОРОВ ====================
async def sniper_loop():
    print("Sniper loop запущен")
    while True:
        try:
            if sniper_state["active"] and sniper_state["target_pair"] and "OTC" not in sniper_state["target_pair"]:
                pair = sniper_state["target_pair"]
                chat_id = sniper_state["chat_id"]
                prices = get_real_candles(pair)
                if prices and len(prices) > 200:
                    rsi = calc_rsi(prices).iloc[-1]
                    ema50 = pd.Series(prices).ewm(span=50).mean().iloc[-1]
                    curr = prices[-1]

                    signal = None
                    if curr > ema50 and rsi < 35:
                        signal = "ВВЕРХ 🟢"
                    elif curr < ema50 and rsi > 65:
                        signal = "ВНИЗ 🔴"

                    if signal:
                        await send_text(chat_id, f"🎯 <b>{pair}</b>\n{signal}\nRSI: {rsi:.0f}\nEMA50 пробита\n⏳ 3 МИН")
                        sniper_state["active"] = False
            await asyncio.sleep(20)
        except Exception as e:
            print(f"Sniper error: {e}")
            await asyncio.sleep(10)

# ==================== ЗАПУСК ====================
async def main():
    print("🚀 БРОДЯГА v3 ЗАПУЩЕН")
    await asyncio.gather(
        telegram_listener(),
        sniper_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
