import os, time, asyncio, cv2
import pandas as pd
import numpy as np
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Stealth Scout ONE BOT running")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/USD", "USD/CAD", "EUR/GBP"]
state = {"last_signal": 0, "waiting_pocket": False, "chat_id": None}

def calc_rsi(prices, period=14):
    s = pd.Series(prices)
    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    return 100 - (100 / (1 + gain/loss))

def get_candles(pair):
    try:
        if not TWELVE_KEY: return None, None, None
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=300&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r:
            print(f"Twelve {pair}: {r}")
            return None, None, None
        vals = list(reversed(r['values']))
        return [float(x['close']) for x in vals], [float(x['high']) for x in vals], [float(x['low']) for x in vals]
    except Exception as e:
        print(e); return None, None, None

def is_open():
    return datetime.now(ZoneInfo("Europe/Moscow")).weekday() < 5

def scouts(closes, highs, lows):
    if len(closes) < 220: return None, 0, []
    prices = np.array(closes)
    rsi = float(calc_rsi(prices).iloc[-1])
    ema200 = pd.Series(prices).ewm(span=200).mean().iloc[-1]
    votes_up, votes_down, reasons = 0, 0, []
    # 1 RSI
    if rsi <= 30: votes_up+=1; reasons.append(f"RSI {rsi:.0f}")
    elif rsi >= 70: votes_down+=1; reasons.append(f"RSI {rsi:.0f}")
    # 2 EMA200
    if prices[-1] < ema200: votes_down+=1; reasons.append("Под EMA200")
    else: votes_up+=1; reasons.append("Над EMA200")
    # 3 Импульс
    impulse = abs(prices[-1]-prices[-7])
    avg_move = np.mean(np.abs(np.diff(prices[-30:])))
    if impulse > avg_move*4:
        reasons.append("Импульс")
        if prices[-1] > prices[-7]: votes_down+=1
        else: votes_up+=1
    # 4 Истощение
    last_range = highs[-1]-lows[-1]
    prev_range = highs[-2]-lows[-2]
    if prev_range>0 and last_range < prev_range*0.5:
        reasons.append("Истощение")
        if closes[-1] > closes[-2]: votes_down+=1
        else: votes_up+=1
    # 5 Доји
    avg_range = np.mean([highs[i]-lows[i] for i in range(-8,-1)])
    if avg_range>0 and last_range < avg_range*0.4:
        reasons.append("Доји")
        if closes[-1] > closes[-2]: votes_down+=1
        else: votes_up+=1
    if votes_up>=3 and votes_up>votes_down: return "ВВЕРХ", votes_up, reasons
    if votes_down>=3 and votes_down>votes_up: return "ВНИЗ", votes_down, reasons
    return None, max(votes_up, votes_down), reasons

def pocket_scouts(photo_path):
    img = cv2.imread(photo_path)
    if img is None: return None, []
    h,w = img.shape[:2]
    chart = img[int(h*0.18):int(h*0.65), int(w*0.02):int(w*0.95)]
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    mask = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    candles=[]
    for x in range(mask.shape[1]-2,0,-2):
        col=np.where(mask[:,x]>0)[0]
        if len(col)>2:
            candles.append({"price": float(chart.shape[0]-col.mean()), "green": bool(green[:,x].max()>0), "size": int(col.max()-col.min())})
    candles=candles[::-1]
    if len(candles)<15: return None, []
    prices=np.array([c["price"] for c in candles]); sizes=np.array([c["size"] for c in candles],float); greens=[c["green"] for c in candles]
    votes_up=votes_down=0; reasons=[]
    last_green=greens[-1]
    if sizes[-1] < sizes[-7:-1].mean()*0.4: reasons.append("Доји"); votes_down+=1 if last_green else 0; votes_up+=1 if not last_green else 0
    if abs(prices[-3]-prices[-7])>12: reasons.append("Импульс"); votes_down+=1 if last_green else 0; votes_up+=1 if not last_green else 0
    if greens[-1]==greens[-2]==greens[-3]: reasons.append("Фейк"); votes_down+=1 if last_green else 0; votes_up+=1 if not last_green else 0
    if sizes[-1] < sizes[-2]*0.5: reasons.append("Истощение"); votes_down+=1 if last_green else 0; votes_up+=1 if not last_green else 0
    ema20=pd.Series(prices).ewm(span=20).mean().iloc[-1]
    if abs(prices[-1]-ema20)>8: reasons.append("EMA"); votes_down+=1 if prices[-1]>ema20 else 0; votes_up+=1 if prices[-1]<ema20 else 0
    if votes_up>=3: return "ВВЕРХ", reasons
    if votes_down>=3: return "ВНИЗ", reasons
    return None, reasons

async def send(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

async def analyze_all(chat_id):
    if not is_open(): await send(chat_id, "Форекс закрыт"); return
    await send(chat_id, "Один бот, 8 мажоров, разведчики пошли... 10 сек")
    async def task(p):
        c,h,l = await asyncio.to_thread(get_candles, p)
        if not c: return (p, None, 0, 0, [])
        d,v,r = scouts(c,h,l)
        return (p,d,v,float(calc_rsi(c).iloc[-1]),r)
    res = await asyncio.gather(*(task(p) for p in MAJORS))
    text="ОТЧЕТ 8 МАЖОРОВ:\n\n"; sig=[]
    for p,d,v,rsi,r in res:
        text+=f"{p}: {d if d else 'ЖДИ'} | {v}/5 | RSI {rsi:.0f}\n"
        if d: sig.append((p,d,v,r))
    if sig:
        sig.sort(key=lambda x:x[2], reverse=True); b=sig[0]
        text+=f"\nЛУЧШИЙ: {b[0]} -> {b[1]} ({b[2]}/5)\n{', '.join(b[3])}"
    else: text+="\nВсе ЖДИ. Не лезь."
    await send(chat_id, text)

async def listener():
    offset=0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r=await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset":offset,"timeout":25})
                for upd in r.json().get("result",[]):
                    offset=upd["update_id"]+1
                    msg=upd.get("message",{}); chat_id=msg.get("chat",{}).get("id")
                    if not chat_id: continue
                    text=msg.get("text","").strip().upper()
                    if text=="/START":
                        await send(chat_id, "Stealth Scout ONE BOT\n\nАНАЛИЗ - 8 мажоров\nEUR/USD - одна пара\nPOCKET - скрин Покет 1м\n/STOP - сброс")
                    elif text=="АНАЛИЗ": asyncio.create_task(analyze_all(chat_id))
                    elif text in MAJORS:
                        if not is_open(): await send(chat_id, "Форекс закрыт"); continue
                        c,h,l=await asyncio.to_thread(get_candles,text)
                        if not c: await send(chat_id, f"{text}: нет свечей"); continue
                        d,v,r=scouts(c,h,l); rsi=float(calc_rsi(c).iloc[-1])
                        await send(chat_id, f"{text}\n{d if d else 'ЖДИ'} | {v}/5 | RSI {rsi:.1f}\n{', '.join(r)}")
                    elif text=="POCKET":
                        state["waiting_pocket"]=True; state["chat_id"]=chat_id
                        await send(chat_id, "Кидай скрин Покет 1м")
                    elif text=="/STOP":
                        state["waiting_pocket"]=False; state["last_signal"]=0
                        await send(chat_id, "Сбросил")
                    if "photo" in msg and state["waiting_pocket"]:
                        if time.time()-state["last_signal"]<60:
                            await send(chat_id, "Кулдаун 60 сек, выходим быстро"); continue
                        fid=msg["photo"][-1]["file_id"]
                        fr=await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id":fid})
                        path=fr.json()["result"]["file_path"]
                        data=await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
                        open("/tmp/screen.jpg","wb").write(data.content)
                        d,r=pocket_scouts("/tmp/screen.jpg")
                        if d: state["last_signal"]=time.time(); await send(chat_id, f"POCKET СИГНАЛ: {d}\n{', '.join(r)}\n1м, зашёл и вышел")
                        else: await send(chat_id, f"POCKET ЖДИ\n{', '.join(r)}")
            except Exception as e:
                print(e); await asyncio.sleep(3)

asyncio.run(listener())
