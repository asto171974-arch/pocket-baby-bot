import os, asyncio, cv2, numpy as np
import pandas as pd
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Brodyaga v3 EMA50")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT",10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY"]
OTC_LIST = ["EUR/USD-OTC", "GBP/USD-OTC"]

state = {"mode": None, "pair": None, "chat_id": None, "last_win_time": 0}

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze_screen(path):
    img = cv2.imread(path)
    if img is None: return None, None
    h, w = img.shape[:2]
    # Координаты с твоего скрина
    chart = img[int(h*0.18):int(h*0.62), 0:int(w*0.88)]
    
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    # Зелёные + красные свечи
    green = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    candles = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    
    prices = []
    for x in range(candles.shape[1]-5, 0, -3):
        col = np.where(candles[:, x] > 0)[0]
        if len(col) > 0:
            prices.append(chart.shape[0] - col.mean())
    if len(prices) < 60: return None, None
    
    prices = prices[::-1]
    ema50 = pd.Series(prices).ewm(span=50).mean().iloc[-1]
    rsi = calc_rsi(prices).iloc[-1]
    curr = prices[-1]
    # Падение/рост за последние 20 свечей
    move = curr - prices[-20]

    # ТВОЯ СТРАТЕГИЯ
    if move < -80 and curr > ema50 and rsi < 48:
        return "ВВЕРХ 🟢", rsi
    if move > 80 and curr < ema50 and rsi > 52:
        return "ВНИЗ 🔴", rsi
    if move > 150 and curr > ema50:
        return "НЕ ПРОДАВАТЬ! Ты на вершине как на скрине 4", rsi
    return None, rsi

async def send_text(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

# ... сюда твой telegram_listener, но добавь обработку фото:
# if "photo" in msg:
#    file_id = msg["photo"][-1]["file_id"]
#    # скачай в /tmp/a.jpg
#    res, rsi = analyze_screen("/tmp/a.jpg")
#    if res: await send_text(chat, f"{res}\nRSI:{rsi:.0f}\nEMA50 пробита, экспирация 1-2м")
#    else: await send_text(chat, f"Нет сетапа. RSI {rsi:.0f}. Жди дно/потолок")

asyncio.run(asyncio.sleep(999999))
