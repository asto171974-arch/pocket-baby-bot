import os, time, random, pandas as pd, httpx, asyncio
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

class FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"V5 REAL OTC running")
    def log_message(self, *args): return

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), FakeHandler).serve_forever()
Thread(target=run_fake_server, daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
BIN_TOKEN = os.getenv("BINARIUM_TOKEN")
BIN_EMAIL = os.getenv("BINARIUM_EMAIL")
BIN_PASS = os.getenv("BINARIUM_PASS")

import asyncio
import json
import websockets
import pandas as pd

<span style="color:red">BINARIUM_WS_URL = "wss://ТВОЙ_URL_ОТ_BINARIUM/API/candles"

<span style="color:red">BINARIUM_TOKEN = "ТВОЙ_ТОКЕН_ОТ_BINARIUM"

async def get_real_candles_B(symbol="EUR/USD OTC", tf="1m", count=100):
    <span style="color:red">headers = {"Authorization": f"Bearer {BINARIUM_TOKEN}"}
    payload = {
        <span style="color:red">"API_action": "get_candles"
        "symbol": symbol,
        "timeframe": tf,
        "count": count
    }
    try:
        <span style="color:red">async with websockets.connect(BINARIUM_WS_URL, extra_headers=headers) as ws:</span>
            await ws.send(json.dumps(payload))
            raw = await ws.recv()
            data = json.loads(raw)
            candles = data.get('candles') or data.get('data') or []
            df = pd.DataFrame(candles, columns=['time','open','high','low','close'])
            return df
    except Exception as e:
        print(f"B fetcher error: {e}")
        return None

def analyze(df):
    if df is None or len(df) < 50:
        return None
    df = df.copy()
    df['ema9'] = df['close'].ewm(span=9).mean()
    df['ema21'] = df['close'].ewm(span=21).mean()
    df['rsi'] = 100 - (100 / (1 + df['close'].diff().clip(lower=0).rolling(14).mean() / (-df['close'].diff().clip(upper=0).rolling(14).mean().abs() + 1e-9)))
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # V5 фильтр: тренд + импульс + свеча
    up_trend = last['ema9'] > last['ema21'] and last['close'] > last['ema9']
    down_trend = last['ema9'] < last['ema21'] and last['close'] < last['ema9']
    
    bullish_engulf = last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']
    bearish_engulf = last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']
    
    if up_trend and last['rsi'] < 70 and bullish_engulf:
        return "CALL", round(last['rsi'],1)
    if down_trend and last['rsi'] > 30 and bearish_engulf:
        return "PUT", round(last['rsi'],1)
    return None

SYMBOLS = ["EUR/USD OTC","GBP/USD OTC","USD/JPY OTC","EUR/JPY OTC","AUD/USD OTC"]

def format_signal(sym, direction, rsi_val, tf="1m"):
    t = datetime.now().strftime("%H:%M:%S")
    return f"🔥 V5 SIGNAL {sym}\nНаправление: {direction}\nТФ: {tf}\nRSI: {rsi_val}\nВремя: {t} (UTC+3)"

import os
from flask import Flask
app = Flask(_name_)
@app.route('/')
def home():return "Bot is running"

if_name_=="_main_":
     port = int(os.environ.get("PORT",10000))
     app.run(host='0.0.0.0,port=port)
