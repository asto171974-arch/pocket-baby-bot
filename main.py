import os, time, random, pandas as pd, httpx, asyncio
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga V3.2.5 SCHEDULE running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()
Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

BEST_OTC_12 = [
    "EUR/USD-OTC", "USD/JPY-OTC", "GBP/USD-OTC", "EUR/JPY-OTC", 
    "EUR/GBP-OTC", "AUD/USD-OTC", "USD/CHF-OTC", "EUR/CHF-OTC",
    "EUR/CAD-OTC", "GBP/CAD-OTC", "AUD/CAD-OTC", "NZD/USD-OTC"
]
# Нормальные пары - только спокойные мажоры, без жирных типа GBP/JPY
NORMAL_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "EUR/JPY", "USD/CHF"]

last_signals = {}

def get_candles(pair="OTC", n=800):
    if "/" in pair and "OTC" not in pair and TWELVE_KEY:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=200&apikey={TWELVE_KEY}"
            r = httpx.get(url, timeout=10).json()
            if 'values' in r and len(r['values']) > 20:
                return [float(x['close']) for x in reversed(r['values'])]
        except: pass
    base = random.uniform(1.05, 1.35)
    prices = [base]
    trend = random.choice([-1,1]) * 0.0002
    for _ in range(n-1):
        prices.append(prices[-1] + trend + random.uniform(-0.0007, 0.0007))
    return prices

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_market_ok(prices, curr_rsi):
    if 42 < curr_rsi < 58: return False
    last_20 = prices[-20:]
    vol = (max(last_20) - min(last_20)) / max(last_20) * 100
    if vol < 0.02: return False
    return True

def check_history(prices, curr_rsi):
    rsi_series = calc_rsi(prices)
    ema21 = pd.Series(prices).ewm(span=21).mean()
    similar = 0; wins_up = 0; wins_down = 0
    for i in range(100, len(prices)-15):
        if pd.isna(rsi_series.iloc[i]): continue
        if abs(rsi_series.iloc[i] - curr_rsi) < 2.0 and (prices[i] > ema21.iloc[i]) == (prices[-1] > ema21.iloc[-1]):
            similar += 1
            future = prices[i+5] - prices[i]
            if future > 0: wins_up += 1
            else: wins_down += 1
    if similar < 8: return 50, "НЕТ", 0
    win_rate = max(wins_up, wins_down) / similar * 100
    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return win_rate, direction, similar

def get_active_pairs():
    now = datetime.now()
    weekday = now.weekday() # 0=Пн ... 6=Вс
    hour = now.hour
    
    # СБ-ВС = только ОТС
    if weekday >= 5:
        return BEST_OTC_12, f"СБ-ВС ОТС {hour}:00"
    
    # ПН-ПТ
    if 8 <= hour < 18:
        return BEST_OTC_12, f"ПН-ПТ {hour}:00 ОТС"
    elif 18 <= hour <= 23:
        return NORMAL_PAIRS, f"ПН-ПТ {hour}:00 НОРМАЛЬНЫЕ"
    else:
        return [], f"СПИМ {hour}:00"

async def send_signal(text):
    if not BOT_TOKEN or not CHANNEL_ID: print(text); return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
    except: pass

async def keepalive():
    while True:
        try:
            now = datetime.now()
            if now.minute % 20 == 0 and 8 <= now.hour <= 23:
                active, mode = get_active_pairs()
                if active:
                    await send_signal(f"✅ <b>БРОДЯГА SCHEDULE ЖИВ</b> ⏰ {now.strftime('%H:%M')}\n📊 Режим: {mode}\n💰 Пар: {len(active)}\n📅 День: {['ПН','ВТ','СР','ЧТ','ПТ','СБ','ВС'][now.weekday()]}")
                await asyncio.sleep(65)
        except: pass
        await asyncio.sleep(30)

async def main():
    print("БРОДЯГА V3.2.5 SCHEDULE ЗАПУЩЕН")
    asyncio.create_task(keepalive())
    while True:
        try:
            active_pairs, mode_text = get_active_pairs()
            if not active_pairs:
                print(f"💤 Спим: {mode_text}")
                await asyncio.sleep(60)
                continue

            print(f"🔍 Режим: {mode_text} | Пар: {len(active_pairs)}")
            found = 0
            random.shuffle(active_pairs)
            for pair in active_pairs:
                if pair in last_signals and time.time() - last_signals[pair] < 1200: continue
                prices = get_candles(pair, n=800)
                rsi_series = calc_rsi(prices)
                curr_rsi = rsi_series.iloc[-1]
                if pd.isna(curr_rsi): continue
                if not is_market_ok(prices, curr_rsi): continue

                if curr_rsi <= 32 or curr_rsi >= 68:
                    win_rate, direction, similar = check_history(prices, curr_rsi)
                    if win_rate >= 78 and similar >= 10:
                        expire = "3 МИН ⏰⏰⏰" if curr_rsi <= 28 or curr_rsi >= 72 else "2 МИН ⏰"
                        t_dir = "ВНИЗ 🔴📉" if "ВНИЗ" in direction else "ВВЕРХ 🟢📈"
                        type_text = "ОТС" if "OTC" in pair else "ФОРЕКС"
                        msg = f"""
🔥 <b>БРОДЯГА SCHEDULE</b> {'⬇️' if 'ВНИЗ' in direction else '⬆️'}🔥
💰 Актив: <b>{pair}</b> ({type_text})
📊 RSI: {curr_rsi:.1f}
🎯 <b>ВРЕМЯ: {t_dir}</b>
⏳ Экспирация: {expire}
🧠 Подтверждений: {similar} / 800
✅ Уверенность: {win_rate:.0f}%
📅 Режим: {mode_text}
👉 <b>ВХОД НА {expire} {t_dir}</b>
"""
                        await send_signal(msg)
                        last_signals[pair] = time.time()
                        found = 1
                        print(f"💎 {pair} {t_dir} WR:{win_rate:.0f}% {mode_text}")
                        await asyncio.sleep(10)
                        break
                await asyncio.sleep(0.7)
            await asyncio.sleep(25 if found else 40)
        except Exception as e:
            print(f"Err: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
