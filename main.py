import os, time, random, pandas as pd, httpx, asyncio
import yfinance as yf
from datetime import datetime, timezone, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"V5.2 BOLTLIVY")
    def log_message(self, *args): return

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT",10000))), FakeHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MSK = timezone(timedelta(hours=3))

NORMAL_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "EUR/JPY", "USD/CHF"]
BEST_OTC_12 = ["EUR/USD-OTC", "USD/JPY-OTC", "GBP/USD-OTC", "EUR/JPY-OTC", "EUR/GBP-OTC", "AUD/USD-OTC"]

YF_MAP = {"EUR/USD":"EURUSD=X","GBP/USD":"GBPUSD=X","USD/JPY":"JPY=X","EUR/JPY":"EURJPY=X","EUR/GBP":"EURGBP=X","AUD/USD":"AUDUSD=X","USD/CHF":"CHF=X"}

last_signals = {}
COOLDOWN = 180

def get_real_candles(pair):
    try:
        clean = pair.replace("-OTC","")
        df = yf.download(tickers=YF_MAP.get(clean,"EURUSD=X"), period="1d", interval="1m", progress=False, auto_adjust=False)
        if df.empty or len(df)<80: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        return df["Close"].tolist()
    except: return None

def calc_rsi(prices):
    s = pd.Series(prices); d = s.diff()
    gain = d.clip(lower=0).rolling(14).mean(); loss = -d.clip(upper=0).rolling(14).mean()
    return 100 - (100/(1+gain/(loss+1e-9)))

def check_history(prices, curr_rsi):
    rsi_s = calc_rsi(prices); ema21 = pd.Series(prices).ewm(span=21).mean()
    similar=0; up=0; down=0
    for i in range(80, len(prices)-10):
        if abs(rsi_s.iloc[i]-curr_rsi)<2.0:
            similar+=1
            if prices[i+5] > prices[i]: up+=1
            else: down+=1
    if similar<5: return 50,"НЕТ",0
    wr = max(up,down)/similar*100
    return wr, ("ВВЕРХ 🟢" if up>down else "ВНИЗ 🔴"), similar

def get_active_pairs():
    now = datetime.now(MSK); h=now.hour
    if now.weekday()>=5 or not (9<=h<18):
        return BEST_OTC_12, f"ОТС {h}:00", True
    return NORMAL_PAIRS, f"REAL {h}:00", False

async def send_signal(t):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id":CHANNEL_ID,"text":t,"parse_mode":"HTML"})

async def main():
    print("V5.2 BOLTLIVY START")
    while True:
        pairs, mode, is_otc = get_active_pairs()
        random.shuffle(pairs)
        for pair in pairs:
            if pair in last_signals and time.time()-last_signals[pair]<COOLDOWN: continue
            prices = get_real_candles(pair)
            if not prices: continue
            rsi = calc_rsi(prices).iloc[-1]
            if pd.isna(rsi): continue
            # ОСЛАБЛЕННЫЕ ФИЛЬТРЫ
            if 48 < rsi < 52: 
                print(f"{pair} RSI {rsi:.1f} - флет, пропуск")
                continue
            if rsi <= 42 or rsi >= 58:
                wr, direction, similar = check_history(prices, rsi)
                print(f"{pair} RSI {rsi:.1f} WR {wr:.0f}% sim {similar} -> {direction}")
                if wr >= 70 and similar >= 5:
                    exp = 2 if is_otc else 3
                    t_dir = "ВНИЗ 🔴📉" if "ВНИЗ" in direction else "ВВЕРХ 🟢📈"
                    msg = f"🔥 <b>V5.2 {wr:.0f}%</b>\n💰 {pair} ({'ОТС' if is_otc else 'ФОРЕКС'})\n📊 RSI {rsi:.1f}\n🎯 {t_dir}\n⏳ {exp} МИН\n{mode}"
                    await send_signal(msg)
                    last_signals[pair]=time.time()
                    await asyncio.sleep(5)
                    break
            await asyncio.sleep(0.5)
        await asyncio.sleep(30)

asyncio.run(main())
