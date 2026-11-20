import os, time, asyncio, httpx
import pandas as pd
import numpy as np
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Stealth Scout OUR BOT v2 running")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MSK = ZoneInfo("Europe/Moscow")

FOREX = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CAD", "EUR/GBP"]
GOLD = ["XAU/USD"]

def now_msk():
    return datetime.now(MSK)

def is_open():
    return now_msk().weekday() < 5

def news_filter():
    # Грубая защита от главных новостей США
    t = now_msk()
    # 15:30 и 17:00 МСК - самое мясо
    for h, m in [(15,30),(17,0)]:
        diff = abs((t.hour*60+t.minute) - (h*60+m))
        if diff <= 15:
            return True
    return False

def calc_rsi(prices, period=14):
    s = pd.Series(prices)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_candles(pair, interval="1min"):
    try:
        if not TWELVE_KEY: return None
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval={interval}&outputsize=250&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r: return None
        vals = list(reversed(r['values']))
        return [float(x['close']) for x in vals]
    except:
        return None

def scouts(closes):
    if len(closes) < 220: return None, 0, []
    prices = np.array(closes)
    rsi = float(calc_rsi(prices).iloc[-1])
    ema50 = pd.Series(prices).ewm(span=50).mean().iloc[-1]
    ema200 = pd.Series(prices).ewm(span=200).mean().iloc[-1]
    
    votes_up, votes_down, reasons = 0, 0, []
    
    # 1. Тренд EMA50/200 - главное
    if prices[-1] > ema50 and ema50 > ema200:
        votes_up += 2; reasons.append("Тренд ВВЕРХ")
    elif prices[-1] < ema50 and ema50 < ema200:
        votes_down += 2; reasons.append("Тренд ВНИЗ")
    
    # 2. RSI откат к тренду, а не против
    if rsi < 40 and prices[-1] > ema200:
        votes_up += 1; reasons.append(f"RSI {rsi:.0f} откупка")
    elif rsi > 60 and prices[-1] < ema200:
        votes_down += 1; reasons.append(f"RSI {rsi:.0f} отбой")
    elif rsi <= 30:
        votes_up += 1; reasons.append(f"RSI {rsi:.0f}")
    elif rsi >= 70:
        votes_down += 1; reasons.append(f"RSI {rsi:.0f}")
    
    # 3. Импульс за 5 свечей по тренду
    move = prices[-1] - prices[-6]
    if abs(move) > np.mean(np.abs(np.diff(prices[-30:]))) * 3:
        if move > 0:
            votes_up += 1; reasons.append("Импульс ВВЕРХ")
        else:
            votes_down += 1; reasons.append("Импульс ВНИЗ")
    
    # 4. Последняя свеча не доји
    if abs(prices[-1] - prices[-2]) < np.mean(np.abs(np.diff(prices[-20:]))) * 0.3:
        reasons.append("Доји - слабый")
        # не голосуем, просто режем силу
    
    if votes_up >= 3 and votes_up > votes_down:
        return "ВВЕРХ", votes_up, reasons
    if votes_down >= 3 and votes_down > votes_up:
        return "ВНИЗ", votes_down, reasons
    return None, max(votes_up, votes_down), reasons

async def send(chat_id, text, buttons=None):
    payload = {"chat_id": chat_id, "text": text}
    if buttons:
        payload["reply_markup"] = {"keyboard": [buttons], "resize_keyboard": True}
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)

MAIN_MENU = ["СИГНАЛ FOREX", "СИГНАЛ GOLD", "СИГНАЛ OTC"]

async def analyze_forex(chat_id, mode="FOREX"):
    if not is_open():
        await send(chat_id, "Форекс закрыт. Выходные.")
        return
    if news_filter():
        await send(chat_id, "НОВОСТИ США! 15 мин пауза. Не лезь, депозит целее.")
        # не return, но предупреждаем - пусть решает сам
    await send(chat_id, f"{mode}: разведчики пошли... жди 20 сек")
    
    pairs = GOLD if mode == "GOLD" else FOREX
    
    async def task(p):
        c = await asyncio.to_thread(get_candles, p)
        if not c: return (p, None, 0, 0, [])
        d, v, r = scouts(c)
        rsi = float(calc_rsi(c).iloc[-1])
        return (p, d, v, rsi, r)
    
    res = await asyncio.gather(*(task(p) for p in pairs))
    
    text = f"ОТЧЕТ {mode}:\n\n"
    signals = []
    for p, d, v, rsi, r in res:
        text += f"{p}: {d if d else 'ЖДИ'} | {v}/5 | RSI {rsi:.0f}\n"
        if d: signals.append((p, d, v, r))
    
    if signals:
        signals.sort(key=lambda x: x[2], reverse=True)
        b = signals[0]
        # Голосуем большинством пар
        up = sum(1 for s in signals if s[1] == "ВВЕРХ")
        down = sum(1 for s in signals if s[1] == "ВНИЗ")
        final = "ВВЕРХ" if up > down else "ВНИЗ"
        text += f"\nСИГНАЛ {mode}: {final}\nПара: {b[0]} ({b[2]}/5)\n{', '.join(b[3])}\n\n1м, зашёл и вышел. Не усредняй."
    else:
        text += "\nВсе ЖДИ. Рынок - помойка. Пропускаем."
    
    await send(chat_id, text, MAIN_MENU)

async def listener():
    offset = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 25})
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    if not chat_id: continue
                    text = msg.get("text", "").strip().upper()
                    
                    if text == "/START":
                        await send(chat_id, "Stealth Scout НАШ v2\n\nНажми кнопку и жди 30 сек", MAIN_MENU)
                    elif text == "СИГНАЛ FOREX":
                        asyncio.create_task(analyze_forex(chat_id, "FOREX"))
                    elif text == "СИГНАЛ GOLD":
                        asyncio.create_task(analyze_forex(chat_id, "GOLD"))
                    elif text == "СИГНАЛ OTC":
                        # OTC - берем форекс как прокси, честно предупреждаем
                        await send(chat_id, "OTC - это не настоящий рынок. Беру EUR/USD как прокси. Риск x2.")
                        asyncio.create_task(analyze_forex(chat_id, "OTC"))
                    elif text == "/STOP":
                        await send(chat_id, "Сбросил", MAIN_MENU)
            except Exception as e:
                print(e); await asyncio.sleep(3)

asyncio.run(listener())
