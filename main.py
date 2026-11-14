import os, asyncio, cv2, numpy as np
import pandas as pd
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Brodyaga Final Bot")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT",10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY"]
OTC_LIST = ["EUR/USD-OTC", "GBP/USD-OTC", "USD/JPY-OTC"]

state = {"mode": None, "pair": None, "chat_id": None, "last_win": 0}

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_major_candles(pair):
    url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=500&apikey={TWELVE_KEY}"
    try:
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r: return None
        return [float(x['close']) for x in reversed(r['values'])]
    except: return None

def check_major(pair):
    prices = get_major_candles(pair)
    if not prices or len(prices) < 200: return None
    ema50 = pd.Series(prices).ewm(span=50).mean().iloc[-1]
    rsi = calc_rsi(prices).iloc[-1]
    price = prices[-1]
    
    # Твоя защита от реванша
    if asyncio.get_event_loop().time() - state["last_win"] < 300:
        return "ЖДИ 5 МИН, ТЫ ТОЛЬКО ЗАБРАЛ"
        
    if price > ema50 and rsi < 40:
        return f"ВВЕРХ 🟢\n{pair}\nRSI {rsi:.0f} под EMA50"
    if price < ema50 and rsi > 60:
        return f"ВНИЗ 🔴\n{pair}\nRSI {rsi:.0f} над EMA50"
    return None

def analyze_otc_photo(path):
    img = cv2.imread(path)
    if img is None: return None, None
    # Координаты с твоего скрина
    chart = img[180:650, 0:670]
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    
    green = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    mask = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    
    prices = []
    for x in range(mask.shape[1]-5, 0, -2):
        col = np.where(mask[:, x] > 0)[0]
        if len(col) > 0:
            prices.append(chart.shape[0] - col.mean())
    if len(prices) < 50: return None, None
    prices = prices[::-1]
    
    ema50 = pd.Series(prices).ewm(span=50).mean().iloc[-1]
    rsi = calc_rsi(prices).iloc[-1]
    price = prices[-1]
    
    # Защита: 3 зелёные подряд = не продавать
    last3 = prices[-3:]
    if last3[-1] > last3[-2] > last3[-3] and price > ema50:
        return "НЕ ПРОДАВАТЬ! 3 зелёные, тренд вверх", rsi
        
    if price > ema50 and rsi < 45:
        return "ВВЕРХ 🟢 OTC\nПробил EMA50 вверх", rsi
    if price < ema50 and rsi > 55:
        return "ВНИЗ 🔴 OTC\nПробил EMA50 вниз", rsi
    return f"ЖДИ, нет сетапа. RSI {rsi:.0f}, цена {'над' if price>ema50 else 'под'} EMA50", rsi

async def send(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

async def send_menu(chat_id):
    kb = [[{"text": f"📈 {p}", "callback_data": f"major_{p}"}] for p in MAJORS]
    kb.append([{"text": "--- OTC ПО ФОТО ---", "callback_data": "ignore"}])
    kb += [[{"text": f"🔥 {p}", "callback_data": f"otc_{p}"}] for p in OTC_LIST]
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "Выбирай:\nМажоры - бот сам\nOTC - кидай скрин 1м", "reply_markup": {"inline_keyboard": kb}})

async def telegram_listener():
    offset = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 25})
                data = r.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    print("UPDATE:", upd) # <-- это покажет в логах

                    # Нажатие кнопки
                    if "callback_query" in upd:
                        call = upd["callback_query"]
                        chat_id = call["message"]["chat"]["id"]
                        data_call = call["data"]
                        print("BUTTON PRESS:", data_call)

                        if data_call == "EUR/USD-OTC":
                            sniper_state["active"] = True
                            sniper_state["target_pair"] = "EUR/USD"
                            sniper_state["chat_id"] = chat_id
                            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                                "chat_id": chat_id,
                                "text": "✅ EUR/USD-OTC выбран\nКидай скрин графика M1, я по EMA50 скажу ВВЕРХ/ВНИЗ/ЖДИ"
                            })
                        # ... остальные пары так же

                    # Фото-скрин от тебя
                    if "message" in upd and "photo" in upd["message"]:
                        chat_id = upd["message"]["chat"]["id"]
                        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": "📸 Скрин получил, анализирую по EMA50..."
                        })
                        # тут твой analyze_otc_screenshot

            except Exception as e:
                print("Listener error:", e)
                await asyncio.sleep(3)

asyncio.run(listener())
