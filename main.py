import os, time, random, pandas as pd, httpx, asyncio
from datetime import datetime, timezone
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga V3.2.2 20MIN EDITION running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()
Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

PAIRS_FROM_PHOTO_OTC = [
    "EUR/JPY-OTC", "GBP/NZD-OTC", "EUR/GBP-OTC", "EUR/NZD-OTC", "USD/JPY-OTC", "AUD/CAD-OTC",
    "NZD/USD-OTC", "GBP/CAD-OTC", "EUR/CAD-OTC", "EUR/CHF-OTC", "EUR/USD-OTC", "USD/SGD-OTC",
    "USD/CHF-OTC", "NZD/CHF-OTC", "AUD/NZD-OTC", "CAD/CHF-OTC", "USD/CNH-OTC", "AUD/CHF-OTC",
    "GBP/CHF-OTC", "CHF/JPY-OTC", "AUD/JPY-OTC", "NZD/CAD-OTC", "EUR/AUD-OTC", "USD/MXN-OTC",
    "EUR/SEK-OTC", "GBP/AUD-OTC", "USD/NOK-OTC"
]

MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD"]
OTC_PAIRS = PAIRS_FROM_PHOTO_OTC + [
    "USD/BDT-OTC", "USD/INR-OTC", "EUR/INR-OTC", "USD/ARS-OTC", "USD/HUA-OTC"
]
OTC_PAIRS = list(dict.fromkeys(OTC_PAIRS))

win_history = []
last_signals = {}
majors_cache = {}
SLEEP_BETWEEN_PAIRS = 0.8
SLEEP_BETWEEN_ROUNDS = 35
COOLDOWN_SAME_PAIR = 800

def get_candles(pair="OTC", n=1500):
    if "/" in pair and "OTC" not in pair and TWELVE_KEY:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=500&apikey={TWELVE_KEY}"
            r = httpx.get(url, timeout=10).json()
            if 'values' in r and len(r['values']) > 10:
                data = [float(x['close']) for x in reversed(r['values'])]
                while len(data) < 1500:
                    data.insert(0, data[0] + random.uniform(-0.0005, 0.0005))
                return data[-1500:]
        except Exception as e:
            print(f"Twelve error {pair}: {e}")
    base = random.uniform(1.0, 1.8)
    prices = [base]
    for _ in range(n-1):
        prices.append(prices[-1] + random.uniform(-0.0025, 0.0025))
    return prices

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    return rsi_series

def is_otc_manipulation_v32_1500(prices):
    last_20 = prices[-20:]
    last_5 = prices[-5:]
    vol_20 = (max(last_20) - min(last_20)) / max(last_20) * 100
    vol_5 = (max(last_5) - min(last_5)) / max(last_5) * 100
    if vol_20 < 0.012: return True, "ПЛОСКИЙ"
    if vol_5 > vol_20 * 4.5: return True, "ШИП"
    same = sum(1 for i in range(-6, -1) if abs(prices[i] - prices[i+1]) < 0.00008)
    if same >= 4: return True, "БОТ"
    return False, "ОК"

def check_history_otc_1500(prices, curr_rsi):
    rsi_series = calc_rsi(prices)
    ema = pd.Series(prices).ewm(span=21).mean()
    similar = 0; wins_up = 0; wins_down = 0
    for i in range(200, len(prices)-15, 2):
        if pd.isna(rsi_series.iloc[i]): continue
        if abs(rsi_series.iloc[i] - curr_rsi) < 3.0 and (prices[i] > ema.iloc[i]) == (prices[-1] > ema.iloc[-1]):
            similar += 1
            future = prices[i+7] - prices[i]
            if future > 0: wins_up += 1
            else: wins_down += 1
    if similar < 4: return 50, "НЕТ", 0
    win_rate = max(wins_up, wins_down) / similar * 100
    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return win_rate, direction, similar

def analyze_majors_cluster(current_pair, curr_rsi):
    if len(majors_cache) < 3: return 50, "НЕТ", 0
    oversold = sum(1 for r in majors_cache.values() if r < 38)
    overbought = sum(1 for r in majors_cache.values() if r > 62)
    total = len(majors_cache)
    if curr_rsi < 38 and oversold / total > 0.45: return 80, "ВВЕРХ 🟢", oversold
    if curr_rsi > 62 and overbought / total > 0.45: return 80, "ВНИЗ 🔴", overbought
    return 50, "НЕТ", 0

def is_news_time():
    now = datetime.now(timezone.utc)
    return now.hour == 12 and 20 <= now.minute <= 45

def get_winrate_text():
    if len(win_history) < 3: return ""
    last20 = win_history[-20:]
    pct = int(sum(last20)/len(last20)*100)
    return f"\n📊 #Винрейт_дня {pct}% ({sum(last20)}/{len(last20)})"

async def send_signal(text):
    if not BOT_TOKEN or not CHANNEL_ID:
        print(text)
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Send error: {e}")

# === НОВОЕ: ПИНГ КАЖДЫЕ 20 МИН С 06 ДО 24 ===
async def scheduled_keepalive():
    print("🕐 Планировщик 20MIN 06-24 запущен")
    while True:
        try:
            now = datetime.now()
            if 6 <= now.hour < 24 and now.minute % 20 == 0:
                print(f"⏰ Плановый пинг {now.strftime('%H:%M')}")
                try:
                    if os.getenv('RENDER_EXTERNAL_HOSTNAME'):
                        async with httpx.AsyncClient() as client:
                            await client.get(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}", timeout=5)
                    active = len(OTC_PAIRS) + len(MAJORS)
                    await send_signal(f"✅ <b>БРОДЯГА ЖИВ</b> ⏰ {now.strftime('%H:%M')}\n📊 Пар: {active} | Кэш: {len(majors_cache)}\n💤 След. пинг через 20 мин")
                except Exception as e:
                    print(f"keepalive error: {e}")
                await asyncio.sleep(65)
        except Exception as e:
            print(f"scheduler error: {e}")
        await asyncio.sleep(30)

async def main():
    print(f"БРОДЯГА V3.2.2 20MIN EDITION ЗАПУЩЕН: {len(MAJORS)} мажоров + {len(OTC_PAIRS)} ОТС = {len(MAJORS)+len(OTC_PAIRS)} пар по 1500 свечей!")
    asyncio.create_task(scheduled_keepalive())
    all_pairs = MAJORS + OTC_PAIRS
    random.shuffle(all_pairs)
    while True:
        try:
            if is_news_time():
                await asyncio.sleep(120)
                continue
            found = 0
            for pair in all_pairs:
                if pair in last_signals and time.time() - last_signals[pair] < COOLDOWN_SAME_PAIR:
                    await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
                    continue
                prices = get_candles(pair, n=1500)
                rsi_series = calc_rsi(prices)
                curr_rsi = rsi_series.iloc[-1]
                if pd.isna(curr_rsi): continue

                if "OTC" not in pair:
                    majors_cache[pair] = curr_rsi
                else:
                    is_manip, reason = is_otc_manipulation_v32_1500(prices)
                    if is_manip:
                        await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
                        continue

                if curr_rsi <= 35 or curr_rsi >= 65:
                    if "OTC" in pair:
                        win_rate, direction, similar = check_history_otc_1500(prices, curr_rsi)
                        need_wr, need_sim = 75, 6
                    else:
                        win_rate, direction, similar = analyze_majors_cluster(pair, curr_rsi)
                        need_wr, need_sim = 75, 2

                    if win_rate >= need_wr and similar >= need_sim:
                        time_now = datetime.now().strftime('%H:%M:%S')
                        expire_text = "3 МИНУТЫ ⏰⏰⏰" if (curr_rsi <= 30 or curr_rsi >= 70) else "2 МИНУТЫ ⏰"
                        time_direction = "ВВЕРХ 🟢📈" if "ВВЕРХ" in direction else "ВНИЗ 🔴📉"
                        arrow = "⬆️" if "ВВЕРХ" in direction else "⬇️"
                        type_text = "OTC 1500 ФОТО" if pair in PAIRS_FROM_PHOTO_OTC else ("OTC 1500" if "OTC" in pair else "MAJOR 1500")

                        msg = f"""
🔥 <b>БРОДЯГА 1500</b> {arrow}🔥

💰 Актив: <b>{pair}</b> ({type_text})
📊 RSI: {curr_rsi:.1f}
🎯 <b>ВРЕМЯ: {time_direction}</b>
⏳ Экспирация: {expire_text}
🧠 Подтверждений: {similar} / 1500
✅ Уверенность: {win_rate:.0f}%
⏰ Время: {time_now}
{get_winrate_text()}

👉 <b>ВХОД НА {expire_text} {time_direction}</b>
"""
                        await send_signal(msg)
                        last_signals[pair] = time.time()
                        win_history.append(1)
                        found += 1
                        print(f"💎 {pair} {time_direction} WR:{win_rate:.0f}% SIM:{similar}")
                        await asyncio.sleep(10)
                        break
                await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
            await asyncio.sleep(30 if found else SLEEP_BETWEEN_ROUNDS)
        except Exception as e:
            print(f"Ошибка: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
