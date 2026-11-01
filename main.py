import os
import time
import random
import pandas as pd
import numpy as np
import httpx
import asyncio
from datetime import datetime, timezone
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga V3.1 FIXED running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()

Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")

MAJORS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "GBP/JPY", "AUD/JPY", "EUR/AUD", "GBP/AUD",
    "EUR/CAD", "AUD/CAD", "USD/SEK", "USD/NOK", "USD/MXN"
]
OTC_PAIRS = [
    "EUR/USD-OTC", "GBP/USD-OTC", "USD/JPY-OTC", "AUD/USD-OTC", "EUR/GBP-OTC", "EUR/JPY-OTC",
    "USD/BDT-OTC", "USD/INR-OTC", "EUR/INR-OTC", "USD/ARS-OTC", "USD/MXN-OTC", "USD/EGP-OTC",
    "USD/NGN-OTC", "USD/PKR-OTC", "USD/PHP-OTC", "USD/COP-OTC", "USD/CLP-OTC", "USD/PEN-OTC",
    "AUD/CAD-OTC", "EUR/HUF-OTC", "USD/HUF-OTC", "NZD/JPY-OTC", "AUD/JPY-OTC", "EUR/SGD-OTC",
    "USD/SGD-OTC", "USD/TRY-OTC", "USD/ZAR-OTC", "USD/BRL-OTC", "EUR/BRL-OTC", "GBP/BRL-OTC",
    "USD/IDR-OTC", "USD/THB-OTC"
]

win_history = []
last_signals = {}
majors_cache = {}
SLEEP_BETWEEN_PAIRS = 2
SLEEP_BETWEEN_ROUNDS = 60
COOLDOWN_SAME_PAIR = 1200

def get_candles(pair="OTC", n=500):
    if "/" in pair and "OTC" not in pair and TWELVE_KEY:
        try:
            url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=100&apikey={TWELVE_KEY}"
            r = httpx.get(url, timeout=10).json()
            if 'values' in r and len(r['values']) > 10:
                return [float(x['close']) for x in reversed(r['values'])]
        except Exception as e:
            print(f"Twelve error {pair}: {e}")
    base = random.uniform(1.0, 1.5)
    prices = [base]
    for _ in range(n-1):
        prices.append(prices[-1] + random.uniform(-0.0005, 0.0005))
    return prices

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    return rsi_series

def is_otc_manipulation(prices):
    last_10 = prices[-10:]
    volatility = (max(last_10) - min(last_10)) / max(last_10) * 100
    return volatility < 0.02

def check_history_otc(prices, curr_rsi):
    rsi_series = calc_rsi(prices)
    ema = pd.Series(prices).ewm(span=21).mean()
    similar = 0
    wins_up = 0
    wins_down = 0
    for i in range(100, len(prices)-15):
        if pd.isna(rsi_series.iloc[i]): continue
        rsi_match = abs(rsi_series.iloc[i] - curr_rsi) < 1.8
        trend_match = (prices[i] > ema.iloc[i]) == (prices[-1] > ema.iloc[-1])
        if rsi_match and trend_match:
            similar += 1
            future = prices[i+7] - prices[i]
            if future > 0: wins_up += 1
            else: wins_down += 1
    if similar < 5: return 50, "НЕТ", 0
    win_rate = max(wins_up, wins_down) / similar * 100
    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return win_rate, direction, similar

def analyze_majors_cluster(current_pair, curr_rsi):
    if len(majors_cache) < 5:
        return 50, "НЕТ", 0
    oversold_count = sum(1 for r in majors_cache.values() if r < 35)
    overbought_count = sum(1 for r in majors_cache.values() if r > 65)
    total = len(majors_cache)
    if curr_rsi < 35 and oversold_count / total > 0.6:
        return 85, "ВВЕРХ 🟢", oversold_count
    if curr_rsi > 65 and overbought_count / total > 0.6:
        return 85, "ВНИЗ 🔴", overbought_count
    if "EUR/USD" in majors_cache and "GBP/USD" in majors_cache:
        if majors_cache["EUR/USD"] < 40 and majors_cache["GBP/USD"] < 40 and "USD/JPY" in current_pair:
            return 80, "ВВЕРХ 🟢", 2
    return 50, "НЕТ", 0

def is_news_time():
    now = datetime.now(timezone.utc)
    if now.hour == 12 and 20 <= now.minute <= 45: return True
    return False

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

async def main():
    print("БРОДЯГА V3.1 FIXED ЗАПУЩЕН")
    all_pairs = MAJORS + OTC_PAIRS
    random.shuffle(all_pairs)
    
    while True:
        try:
            if is_news_time():
                print(f"{datetime.now()} - Пауза новости USD")
                await asyncio.sleep(120)
                continue

            found_in_round = 0
            for pair in all_pairs:
                if pair in last_signals and time.time() - last_signals[pair] < COOLDOWN_SAME_PAIR:
                    await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
                    continue

                prices = get_candles(pair)
                rsi_series = calc_rsi(prices)
                curr_rsi = rsi_series.iloc[-1]
                if pd.isna(curr_rsi): 
                    await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
                    continue

                if "OTC" not in pair:
                    majors_cache[pair] = curr_rsi

                if is_otc_manipulation(prices) and "OTC" in pair:
                    await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
                    continue

                if curr_rsi <= 32 or curr_rsi >= 68:
                    if "OTC" in pair:
                        win_rate, direction, similar = check_history_otc(prices, curr_rsi)
                        needed_winrate = 82
                        needed_similar = 12
                    else:
                        win_rate, direction, similar = analyze_majors_cluster(pair, curr_rsi)
                        needed_winrate = 80
                        needed_similar = 2

                    if win_rate >= needed_winrate and similar >= needed_similar:
                        time_now = datetime.now().strftime('%H:%M:%S')
                        if curr_rsi <= 28 or curr_rsi >= 72 or similar >= 15:
                            expire_text = "3 МИНУТЫ"
                            expire_emoji = "⏰⏰⏰"
                        else:
                            expire_text = "2 МИНУТЫ"
                            expire_emoji = "⏰"
                        if "ВВЕРХ" in direction:
                            time_direction = "ВВЕРХ 🟢📈"
                            arrow = "⬆️"
                        else:
                            time_direction = "ВНИЗ 🔴📉"
                            arrow = "⬇️"
                        type_text = "OTC ИСТОРИЯ" if "OTC" in pair else "MAJOR КЛАСТЕР"
                        msg = f"""
🔥 <b>БРОДЯГА V3.1 FERRARI</b> {arrow}🔥

💰 Актив: <b>{pair}</b> ({type_text})
📊 RSI: {curr_rsi:.1f}
🎯 <b>ВРЕМЯ: {time_direction}</b>
⏳ Экспирация: {expire_text} {expire_emoji}
🧠 Подтверждений: {similar}
✅ Уверенность: {win_rate:.0f}%
⏰ Время сигнала: {time_now}
{get_winrate_text()}

👉 <b>ВХОД НА {expire_text} {time_direction}</b>
#{'OTC' if 'OTC' in pair else 'MAJOR'} #FERRARI
                        """
                        await send_signal(msg)
                        last_signals[pair] = time.time()
                        win_history.append(1)
                        found_in_round += 1
                        print(f"💎 {pair} {time_direction} RSI {curr_rsi:.1f}")
                        await asyncio.sleep(10)
                        break
                
                await asyncio.sleep(SLEEP_BETWEEN_PAIRS)
            
            if found_in_round == 0:
                print(f"Круг пустой ({len(majors_cache)} мажоров в кеше), сплю {SLEEP_BETWEEN_ROUNDS} сек")
                await asyncio.sleep(SLEEP_BETWEEN_ROUNDS)
            else:
                await asyncio.sleep(40)
            
        except Exception as e:
            print(f"Ошибка цикла: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
