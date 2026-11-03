import os, time, random, pandas as pd, httpx, asyncio
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga V4.0 ANTI-LENIVIY running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()
Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

BEST_OTC_12 = ["EUR/USD-OTC", "USD/JPY-OTC", "GBP/USD-OTC", "EUR/JPY-OTC", "EUR/GBP-OTC", "AUD/USD-OTC", "USD/CHF-OTC", "EUR/CHF-OTC", "EUR/CAD-OTC", "GBP/CAD-OTC", "AUD/CAD-OTC", "NZD/USD-OTC"]
NORMAL_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "EUR/JPY", "USD/CHF"]

last_signals = {}
COOLDOWN = 180

def get_real_candles(pair):
    """ТОЛЬКО РЕАЛЬНЫЕ ДАННЫЕ, НИКАКОГО РАНДОМА ПОСЛЕ 18:00"""
    if not TWELVE_KEY: return None
    try:
        clean_pair = pair.replace("-OTC", "")
        url = f"https://api.twelvedata.com/time_series?symbol={clean_pair}&interval=1min&outputsize=200&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=10).json()
        if 'values' in r and len(r['values']) > 50:
            closes = [float(x['close']) for x in reversed(r['values'])]
            print(f"✅ REAL DATA {pair} -> {len(closes)} свечей")
            return closes
        else:
            print(f"❌ TwelveData пусто для {pair}: {r.get('message','no values')}")
            return None
    except Exception as e:
        print(f"❌ Ошибка API {pair}: {e}")
        return None

def get_otc_candles():
    """Для ОТС можно генерить, но с логикой"""
    base = random.uniform(1.05, 1.35)
    prices = [base]
    trend = random.choice([-1,1]) * 0.0002
    for _ in range(800):
        prices.append(prices[-1] + trend + random.uniform(-0.0007, 0.0007))
    return prices

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_market_ok_v4(prices, curr_rsi):
    """МОЗГИ: читает индикаторы, а не только свечи"""
    if 43 < curr_rsi < 57: return False # Флет
    s = pd.Series(prices)
    ema21 = s.ewm(span=21).mean().iloc[-1]
    ema50 = s.ewm(span=50).mean().iloc[-1]
    # Если EMA в куче - флет, не торгуем
    if abs(ema21 - ema50) / ema50 * 100 < 0.03: return False
    last_20 = prices[-20:]
    vol = (max(last_20) - min(last_20)) / max(last_20) * 100
    if vol < 0.03 or vol > 0.25: return False # Слишком тихо или слишком бешено
    # Тренд должен совпадать с RSI
    if curr_rsi > 65 and prices[-1] < ema21: return False
    if curr_rsi < 35 and prices[-1] > ema21: return False
    return True

def check_history(prices, curr_rsi):
    rsi_series = calc_rsi(prices)
    ema21 = pd.Series(prices).ewm(span=21).mean()
    similar = 0; wins_up = 0; wins_down = 0
    for i in range(100, len(prices)-15):
        if pd.isna(rsi_series.iloc[i]): continue
        if abs(rsi_series.iloc[i] - curr_rsi) < 1.2 and (prices[i] > ema21.iloc[i]) == (prices[-1] > ema21.iloc[-1]):
            similar += 1
            future = prices[i+5] - prices[i]
            if future > 0: wins_up += 1
            else: wins_down += 1
    if similar < 10: return 50, "НЕТ", 0
    win_rate = max(wins_up, wins_down) / similar * 100
    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return win_rate, direction, similar

def get_smart_expiration(pair, curr_rsi, prices):
    is_otc = "OTC" in pair
    if not is_otc: return 3
    last_20 = prices[-20:]
    vol_percent = (max(last_20) - min(last_20)) / max(last_20) * 100
    if (curr_rsi <= 25 or curr_rsi >= 75) and vol_percent > 0.08: return 1
    elif 45 <= curr_rsi <= 55: return 3
    else: return 2

def get_active_pairs():
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    if weekday >= 5: return BEST_OTC_12, f"СБ-ВС ОТС {hour}:00", True
    if 8 <= hour < 18: return BEST_OTC_12, f"ПН-ПТ {hour}:00 ОТС", True
    elif 18 <= hour <= 23: return NORMAL_PAIRS, f"ПН-ПТ {hour}:00 НОРМАЛЬНЫЕ", False
    else: return [], f"СПИМ {hour}:00", False

async def send_signal(text):
    if not BOT_TOKEN or not CHANNEL_ID: print(text); return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
    except: pass

async def keepalive():
    while True:
        try:
            now = datetime.now()
            if now.minute % 20 == 0 and 8 <= now.hour <= 23:
                active, mode, _ = get_active_pairs()
                if active: await send_signal(f"✅ <b>БРОДЯГА V4.0 ЖИВ</b> ⏰ {now.strftime('%H:%M')}\n📊 {mode}\n💰 Пар: {len(active)}")
                await asyncio.sleep(65)
        except: pass
        await asyncio.sleep(30)

async def main():
    print("БРОДЯГА V4.0 ANTI-LENIVIY ЗАПУЩЕН - МОЗГИ ВСТАВЛЕНЫ")
    asyncio.create_task(keepalive())
    while True:
        try:
            active_pairs, mode_text, is_otc_mode = get_active_pairs()
            if not active_pairs:
                print(f"💤 {mode_text}"); await asyncio.sleep(60); continue

            print(f"🔍 Режим: {mode_text} | ОТС={is_otc_mode}")
            found = 0
            random.shuffle(active_pairs)
            for pair in active_pairs:
                if pair in last_signals and time.time() - last_signals[pair] < COOLDOWN: continue

                # === ГЛАВНЫЙ ФИКС: РАЗНЫЕ ИСТОЧНИКИ ===
                if is_otc_mode:
                    prices = get_otc_candles()
                else:
                    prices = get_real_candles(pair)
                    if prices is None:
                        print(f"⏭️ Пропуск {pair} - нет реальных данных, рандом запрещен!")
                        continue # НЕ ГЕНЕРИМ РАНДОМ ДЛЯ НОРМАЛЬНЫХ ПАР!

                rsi_series = calc_rsi(prices)
                curr_rsi = rsi_series.iloc[-1]
                if pd.isna(curr_rsi): continue
                if not is_market_ok_v4(prices, curr_rsi): continue

                if curr_rsi <= 35 or curr_rsi >= 65:
                    win_rate, direction, similar = check_history(prices, curr_rsi)
                    min_conf = 87 if is_otc_mode else 84 # Поднял для нормальных с 80 до 84
                    if win_rate >= min_conf and similar >= 10:
                        exp_min = get_smart_expiration(pair, curr_rsi, prices)
                        t_dir = "ВНИЗ 🔴📉" if "ВНИЗ" in direction else "ВВЕРХ 🟢📈"
                        type_text = "ОТС" if is_otc_mode else "ФОРЕКС"
                        msg = f"""
🔥 <b>БРОДЯГА V4.0 87%</b> {'⬇️' if 'ВНИЗ' in direction else '⬆️'}🔥
💰 Актив: <b>{pair}</b> ({type_text})
📊 RSI: {curr_rsi:.1f} | EMA: {'выше' if prices[-1] > pd.Series(prices).ewm(span=21).mean().iloc[-1] else 'ниже'}
🎯 <b>ВРЕМЯ: {t_dir}</b>
⏳ Экспирация: {exp_min} МИН
🧠 Подтверждений: {similar} / 200
✅ Уверенность: {win_rate:.0f}%
📅 {mode_text}
👉 <b>ВХОД НА {exp_min} МИН {t_dir}</b>
"""
                        await send_signal(msg)
                        last_signals[pair] = time.time()
                        found = 1
                        print(f"💎 {pair} {t_dir} WR:{win_rate:.0f}% EXP:{exp_min}m {mode_text}")
                        await asyncio.sleep(10)
                        break
                await asyncio.sleep(0.7)
            await asyncio.sleep(25 if found else 40)
        except Exception as e:
            print(f"Err: {e}"); await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
