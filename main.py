import os, time, asyncio, cv2
import pandas as pd
import numpy as np
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from tvdata import TvDataFeed, Interval

tv_feed = TvDataFeed()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Stealth Scout v4 Pocket + Binarium")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CAD", "EUR/GBP"]

state = {"waiting": False, "platform": None, "chat_id": None, "last_pocket": 0, "last_binarium": 0, "last_major": 0}

def calc_rsi(prices, period=14):
    s = pd.Series(prices)
    d = s.diff()
    gain = d.where(d > 0, 0).rolling(period).mean()
    loss = -d.where(d < 0, 0).rolling(period).mean()
    return 100 - (100 / (1 + gain/loss))

def get_candles(pair):
    symbol = pair.replace("/", "")
    try:
        df = tv_feed.get_df(symbol=symbol, exchange='FX', interval=Interval.in_1_minute, n_bars=300)
        if df is not None and len(df) >= 220:
            return df['close'].tolist(), df['high'].tolist(), df['low'].tolist()
    except: pass
    try:
        if TWELVE_KEY:
            url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=300&apikey={TWELVE_KEY}"
            r = httpx.get(url, timeout=15).json()
            if 'values' in r:
                vals = list(reversed(r['values']))
                return [float(x['close']) for x in vals], [float(x['high']) for x in vals], [float(x['low']) for x in vals]
    except: pass
    return None, None, None

def is_market_open():
    return datetime.now(ZoneInfo("Europe/Moscow")).weekday() < 5

def scouts_major(closes, highs, lows):
    if len(closes) < 220: return None, 0, []
    prices = np.array(closes)
    curr_rsi = calc_rsi(prices).iloc[-1]
    ema200 = pd.Series(prices).ewm(span=200).mean().iloc[-1]
    votes_up, votes_down, reasons = 0, 0, []
    if curr_rsi <= 30: votes_up += 1; reasons.append("RSI перепродан")
    elif curr_rsi >= 70: votes_down += 1; reasons.append("RSI перекуплен")
    if prices[-1] < ema200: votes_down += 1; reasons.append("Под EMA200")
    else: votes_up += 1; reasons.append("Над EMA200")
    impulse = abs(prices[-1] - prices[-7])
    if impulse > np.mean(np.abs(np.diff(prices[-30:]))) * 4:
        reasons.append("Импульс")
        if prices[-1] > prices[-7]: votes_down += 1
        else: votes_up += 1
    last_range = highs[-1]-lows[-1]
    if highs[-2]-lows[-2] > 0 and last_range < (highs[-2]-lows[-2])*0.5:
        reasons.append("Истощение")
        if closes[-1] > closes[-2]: votes_down += 1
        else: votes_up += 1
    if votes_up >= 3 and votes_up > votes_down: return "ВВЕРХ", votes_up, reasons
    if votes_down >= 3 and votes_down > votes_up: return "ВНИЗ", votes_down, reasons
    return None, max(votes_up, votes_down), reasons

def extract_screen(photo_path):
    img = cv2.imread(photo_path)
    if img is None: return []
    h, w = img.shape[:2]
    chart = img[int(h*0.18):int(h*0.65), int(w*0.02):int(w*0.95)]
    if chart.size == 0: return []
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    mask = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    candles = []
    for x in range(mask.shape[1]-2, 0, -2):
        col = np.where(mask[:, x] > 0)[0]
        if len(col) > 2:
            candles.append({"price": float(chart.shape[0]-col.mean()), "green": bool(green[:,x].max()>0), "size": int(col.max()-col.min())})
    return candles[::-1]

def scouts_otc(candles, platform):
    if len(candles) < 15: return None, 0, []
    prices = np.array([c["price"] for c in candles])
    sizes = np.array([c["size"] for c in candles], dtype=float)
    greens = [c["green"] for c in candles]
    last_green = greens[-1]
    votes_up, votes_down, reasons = 0, 0, []
    
    # веса под платформы
    # Pocket: импульс и фейк важнее, Binarium: доји и истощение важнее
    def add_vote(weight=1):
        nonlocal votes_up, votes_down
        if last_green: votes_down += weight
        else: votes_up += weight

    # 1. Доји
    avg_size = sizes[-7:-1].mean()
    if sizes[-1] < avg_size * 0.4:
        reasons.append("Доји"); add_vote(2 if platform=="binarium" else 1)
    # 2. Импульс
    impulse = abs(prices[-3]-prices[-7])
    if impulse > 12:
        reasons.append(f"Импульс {impulse:.0f}"); add_vote(2 if platform=="pocket" else 1)
    # 3. Фейк 3 одинаковые
    if greens[-1]==greens[-2]==greens[-3]:
        reasons.append("Фейк"); add_vote(2 if platform=="pocket" else 1)
    # 4. Истощение
    if sizes[-1] < sizes[-2]*0.5:
        reasons.append("Истощение"); add_vote(2 if platform=="binarium" else 1)
    # 5. EMA откат
    ema20 = pd.Series(prices).ewm(span=20).mean().iloc[-1]
    if abs(prices[-1]-ema20) > 8:
        reasons.append("Откат EMA")
        if prices[-1] > ema20: votes_down += 1
        else: votes_up += 1

    max_votes = 6 if platform=="binarium" else 6
    need = 3
    if votes_up >= need and votes_up > votes_down: return "ВВЕРХ", votes_up, reasons
    if votes_down >= need and votes_down > votes_up: return "ВНИЗ", votes_down, reasons
    return None, max(votes_up, votes_down), reasons

async def send(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

async def analyze_all(chat_id):
    if not is_market_open():
        await send(chat_id, "Форекс закрыт. Иди в POCKET или BINARIUM")
        return
    await send(chat_id, "Сканирую 8 мажоров...")
    async def task(pair):
        c,h,l = await asyncio.to_thread(get_candles, pair)
        if not c: return (pair, None, 0)
        d,v,_ = scouts_major(c,h,l)
        return (pair, d, v)
    results = await asyncio.gather(*(task(p) for p in MAJORS))
    text = "8 МАЖОРОВ:\n\n"
    for pair,d,v in results:
        text += f"{pair}: {d if d else 'ЖДИ'} | {v}/5\n"
    await send(chat_id, text)

async def listener():
    offset = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 25})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"]+1
                    msg = upd.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    if not chat_id: continue
                    text = msg.get("text", "").strip().upper()

                    if text == "/START":
                        await send(chat_id, "Stealth Scout v4\n\nPOCKET - разведка Pocket OTC\nBINARIUM - разведка Binarium OTC\nАНАЛИЗ - 8 мажоров\nEUR/USD - один мажор\n\nКидай скрин после POCKET/BINARIUM")
                    elif text == "POCKET":
                        state.update({"waiting": True, "platform": "pocket", "chat_id": chat_id})
                        await send(chat_id, "POCKET активен. Кидай скрин 1м. Импульс+фейк в приоритете.")
                    elif text == "BINARIUM":
                        state.update({"waiting": True, "platform": "binarium", "chat_id": chat_id})
                        await send(chat_id, "BINARIUM активен. Кидай скрин 1м. Доји+истощение в приоритете.")
                    elif text == "АНАЛИЗ":
                        asyncio.create_task(analyze_all(chat_id))
                    elif text in MAJORS:
                        if time.time()-state["last_major"]<60:
                            await send(chat_id, "Кулдаун 60 сек"); continue
                        c,h,l = await asyncio.to_thread(get_candles, text)
                        if not c: await send(chat_id, "Нет свечей"); continue
                        d,v,reasons = scouts_major(c,h,l)
                        state["last_major"]=time.time()
                        await send(chat_id, f"{text}: {d if d else 'ЖДИ'} {v}/5\n{', '.join(reasons)}")
                    elif "photo" in msg and state["waiting"]:
                        fid = msg["photo"][-1]["file_id"]
                        fr = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": fid})
                        path = fr.json()["result"]["file_path"]
                        data = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
                        open("/tmp/screen.jpg","wb").write(data.content)
                        plat = state["platform"]
                        key = "last_pocket" if plat=="pocket" else "last_binarium"
                        if time.time()-state[key] < 60:
                            await send(chat_id, f"Кулдаун 60 сек на {plat.upper()}, быстро выходим"); continue
                        candles = extract_screen("/tmp/screen.jpg")
                        d,v,reasons = scouts_otc(candles, plat)
                        if d:
                            state[key]=time.time()
                            await send(chat_id, f"{plat.upper()} СИГНАЛ: {d}\nРазведчики: {v}\n{', '.join(reasons)}\nЭкспирация 1м. Зашёл-вышел.")
                        else:
                            await send(chat_id, f"{plat.upper()}: ЖДИ\n{', '.join(reasons)}")
                        # остаёмся в режиме для следующего скрина
            except Exception as e:
                print(e); await asyncio.sleep(3)

asyncio.run(listener())
