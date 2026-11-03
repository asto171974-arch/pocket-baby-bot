import os, time, random, pandas as pd, httpx, asyncio
import yfinance as yf
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga V5.1 FIXED running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()
Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

BEST_OTC_12 = ["EUR/USD-OTC", "USD/JPY-OTC", "GBP/USD-OTC", "EUR/JPY-OTC", "EUR/GBP-OTC", "AUD/USD-OTC", "USD/CHF-OTC", "EUR/CHF-OTC"]
NORMAL_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "EUR/JPY", "USD/CHF"]

YF_MAP = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "EUR/JPY": "EURJPY=X", "EUR/GBP": "EURGBP=X", "AUD/USD": "AUDUSD=X",
    "USD/CHF": "CHF=X", "EUR/CHF": "EURCHF=X", "USD/CAD": "CAD=X", "EUR/CAD": "EURCAD=X"
}

last_signals = {}
COOLDOWN = 180
MSK = timezone(timedelta(hours=3))

def get_real_candles(pair):
    """БЕСПЛАТНО, без ключей, работает и для ОТС"""
    try:
        clean = pair.replace("-OTC", "")
        yf_sym = YF_MAP.get(clean, "EURUSD=X")
        df = yf.download(tickers=yf_sym, period="1d", interval="1m", progress=False, auto_adjust=False)
        if df.empty or len(df) < 80:
            print(f"❌ Yahoo пусто для {pair}")
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        closes = df["Close"].tolist()
        print(f"✅ REAL {pair} -> {len(closes)} свечей")
        return closes
    except Exception as e:
        print(f"❌ Ошибка {pair}: {e}")
        return None

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def is_market_ok_v4(prices, curr_rsi):
    if 43 < curr_rsi < 57: return False
    s = pd.Series(prices)
    ema21 = s.ewm(span=21).mean().iloc[-1]
    ema50 = s.ewm(span=50).mean().iloc[-1]
    if abs(ema21 - ema50) / ema50 * 100 < 0.03: return False
    last_20 = prices[-20:]
    vol = (max(last_20) - min(last_20)) / max(last_20) * 100
    if vol < 0.03 or vol > 0.25: return False
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
    now = datetime.now(MSK)
    weekday = now.weekday()
    hour = now.hour
    # ИСПРАВЛЕННАЯ ЛОГИКА КАК ТЫ ПРОСИЛ
    if weekday >= 5: # Сб-Вс всегда ОТС
        return BEST_OTC_12, f"СБ-ВС ОТС {hour}:00", True
    if 9 <= hour < 18: # День - только реал
        return NORMAL_PAIRS, f"ПН-ПТ {hour}:00 REAL ФОРЕКС", False
    else: # Вечер/ночь - ОТС
        return BEST_OTC_12, f"ПН-ПТ {hour}:00 ОТС", True

async def send_signal(text):
    if not BOT_TOKEN or not CHANNEL_ID: print(text); return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})
    except: pass

async def keepalive():
    while True:
        try:
            now = datetime.now(MSK)
            if now.minute % 20 == 0 and 8 <= now.hour <= 23:
                active, mode, _ = get_active_pairs()
                if active: await send_signal(f"✅ <b>БРОДЯГА V5.1 ЖИВ</b> ⏰ {now.strftime('%H:%M')}\n📊 {mode}\n💰 Пар: {len(active)}")
                await asyncio.sleep(65)
        except: pass
        await asyncio.sleep(30)

async def main():
    print("БРОДЯГА V5.1 FIXED ЗАПУЩЕН")
    asyncio.create_task(keepalive())
    while True:
        try:
            active_pairs, mode_text, is_otc_mode = get_active_pairs()
            if not active_pairs:
                print(f"💤 {mode_text}"); await asyncio.sleep(60); continue

            print(f"🔍 {mode_text} | ОТС={is_otc_mode}")
            found = 0
            random.shuffle(active_pairs)
            for pair in active_pairs:
                if pair in last_signals and time.time() - last_signals[pair] < COOLDOWN: continue

                prices = get_real_candles(pair) # Теперь всегда реал
                if prices is None: continue

                rsi_series = calc_rsi(prices)
                curr_rsi = rsi_series.iloc[-1]
                if pd.isna(curr_rsi): continue
                if not is_market_ok_v4(prices, curr_rsi): continue

                if curr_rsi <= 35 or curr_rsi >= 65:
                    win_rate, direction, similar = check_history(prices, curr_rsi)
                    min_conf = 84 if is_otc_mode else 87 # Днем строже
                    if win_rate >= min_conf and similar >= 10:
                        exp_min = get_smart_expiration(pair, curr_rsi, prices)
                        t_dir = "ВНИЗ 🔴📉" if "ВНИЗ" in direction else "ВВЕРХ 🟢📈"
                        type_text = "ОТС" if is_otc_mode else "ФОРЕКС"
                        msg = f"""
🔥 <b>БРОДЯГА V5.1 {win_rate:.0f}%</b> {'⬇️' if 'ВНИЗ' in direction else '⬆️'}🔥
💰 Актив: <b>{pair}</b> ({type_text})
📊 RSI: {curr_rsi:.1f}
🎯 <b>ВРЕМЯ: {t_dir}</b>
⏳ Экспирация: {exp_min} МИН
🧠 Подтверждений: {similar}
✅ Уверенность: {win_rate:.0f}%
📅 {mode_text}
"""
                        await send_signal(msg)
                        last_signals[pair] = time.time()
                        found = 1
                        print(f"💎 {pair} {t_dir} WR:{win_rate:.0f}%")
                        await asyncio.sleep(10)
                        break
                await asyncio.sleep(0.7)
            await asyncio.sleep(25 if found else 40)
        except Exception as e:
            print(f"Err: {e}"); await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
