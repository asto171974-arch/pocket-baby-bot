import os
import asyncio
import pandas as pd
from datetime import datetime, timezone, timedelta
from telegram import Bot
from twelvedata import TDClient

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TD_KEY = os.getenv("TWELVEDATA_API_KEY")

bot = Bot(token=BOT_TOKEN)
td_client = TDClient(apikey=TD_KEY)

MSK = timezone(timedelta(hours=3))

REAL_PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CHF"]
OTC_PAIRS = ["EUR/USD OTC", "GBP/USD OTC", "EUR/JPY OTC", "AUD/USD OTC", "GBP/JPY OTC", "EUR/GBP OTC"]

def get_current_pairs():
    hour = datetime.now(MSK).hour
    return (REAL_PAIRS, "REAL") if 9 <= hour < 18 else (OTC_PAIRS, "OTC")

def parse_to_df(data):
    df = pd.DataFrame(data)
    df[["open","high","low","close"]] = df[["open","high","low","close"]].astype(float)
    return df.iloc[::-1].reset_index(drop=True)

async def get_candles(symbol: str):
    base = symbol.replace(" OTC", "")
    try:
        ts = td_client.time_series(symbol=base, interval="1min", outputsize=100, timezone="UTC").as_json()
        if not ts or "values" not in ts: return None
        return parse_to_df(ts["values"])
    except Exception as e:
        print(f"ERR {symbol}: {e}")
        return None

def analyze(df):
    if df is None or len(df) < 60: return None
    df['ema9'] = df['close'].ewm(span=9).mean()
    df['ema21'] = df['close'].ewm(span=21).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    last = df.iloc[-1]; prev = df.iloc[-2]
    if 45 < last['rsi'] < 55: return None
    if abs(last['ema9'] - last['ema21']) / last['close'] < 0.00015: return None
    up = last['ema9'] > last['ema21'] > last['ema50'] and last['close'] > last['ema9']
    down = last['ema9'] < last['ema21'] < last['ema50'] and last['close'] < last['ema9']
    bull_eng = last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bear_eng = last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']
    if up and last['rsi'] < 68 and bull_eng: return "CALL", round(last['rsi'],1)
    if down and last['rsi'] > 32 and bear_eng: return "PUT", round(last['rsi'],1)
    return None

async def send_signal(symbol, direction, rsi, mode):
    hour = datetime.now(MSK).strftime("%H:%M")
    icon = "🟢" if direction == "CALL" else "🔴"
    txt = f"{icon} V5 {mode} {hour} MSK\nПара: {symbol}\nСигнал: {direction}\nRSI: {rsi}\nТФ: 1m"
    await bot.send_message(chat_id=CHANNEL_ID, text=txt)

async def job():
    while True:
        try:
            pairs, mode = get_current_pairs()
            print(f"[{datetime.now(MSK).strftime('%H:%M')}] {mode}")
            for symbol in pairs:
                df = await get_candles(symbol)
                res = analyze(df)
                if res:
                    d, r = res
                    await send_signal(symbol, d, r, mode)
                    await asyncio.sleep(1.5)
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f"job error: {e}")
        await asyncio.sleep(60)

if __name__ == "__main__":
    print("Bot V5 started")
    asyncio.run(job())
