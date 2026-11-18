import os, time, asyncio, cv2, json
import pandas as pd
import numpy as np
import httpx
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from zoneinfo import ZoneInfo
from tvdata import TvDataFeed, Interval

tv_feed = TvDataFeed()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Brodyaga v3 running")
    def log_message(self, *args): pass

Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TWELVE_KEY = os.getenv("TWELVEDATA_API_KEY")
MAJORS = ["EUR/USD", "GBP/USD", "USD/JPY", "EUR/JPY","EUR/CAD","EUR/GBP","USD/SEK","AUD/JPY","USD/ZAR","USD/CNH","CAD/JPY","USD/CHF","GBP/JPY","NZD/USD","USD/CAD","GBP/CHF", "AUD/USD"]
sniper_state = {"waiting_photo": False, "chat_id": None, "last_signal_time": 0, "mode": None, "sync_time": 0, "sync_dir": None, "sync_chat": None}
TRAIN_DIR = "/tmp/train"
os.makedirs(TRAIN_DIR, exist_ok=True)
DATASET = os.path.join(TRAIN_DIR, "dataset.csv")
MODEL_FILE = os.path.join(TRAIN_DIR, "model.json")

def calc_rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def get_from_tv(pair):
    try:
        symbol = pair.replace("/", "")
        df = None
        try:
            df = tv_feed.get_df(symbol=symbol, exchange='FX', interval=Interval.in_1_minute, n_bars=1000)
        except:
            res = tv_feed.get_quote(symbol=symbol, exchange='FX', interval=Interval.in_1_minute, n_bars=1000)
            df = res[0] if isinstance(res, tuple) else res
        if df is None or len(df) < 300:
            return None
        return df['close'].tolist()
    except Exception as e:
        print(f"ТВ ошибка {pair}: {e}")
        return None

def get_from_twelve(pair):
    try:
        if not TWELVE_KEY: return None
        url = f"https://api.twelvedata.com/time_series?symbol={pair}&interval=1min&outputsize=1000&apikey={TWELVE_KEY}"
        r = httpx.get(url, timeout=15).json()
        if 'values' not in r: return None
        return [float(x['close']) for x in reversed(r['values'])]
    except:
        return None

def get_real_candles(pair):
    # Сначала ТВ, если не вышло - TwelveData
    prices = get_from_tv(pair)
    if prices and len(prices) >= 300:
        return prices
    print(f"{pair}: ТВ не отдало, иду в TwelveData")
    return get_from_twelve(pair)

def is_market_open():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    if now.weekday() >= 5: return False
    if now.weekday() == 0 and now.hour < 3: return False
    return True

def extract_candles_from_screen(photo_path):
    img = cv2.imread(photo_path)
    if img is None: return []
    h, w = img.shape[:2]
    chart = img[int(h*0.15):int(h*0.70), int(w*0.05):int(w*0.98)]
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([35,40,40]), np.array([85,255,255]))
    red1 = cv2.inRange(hsv, np.array([0,40,40]), np.array([10,255,255]))
    red2 = cv2.inRange(hsv, np.array([160,40,40]), np.array([180,255,255]))
    mask = cv2.bitwise_or(green, cv2.bitwise_or(red1, red2))
    candles = []
    x = 0
    while x < mask.shape[1]:
        col = np.where(mask[:, x] > 0)[0]
        if len(col) > 5:
            top, bottom = col.min(), col.max()
            center = (top + bottom) / 2
            is_green = green[:, x].max() > 0
            candles.append({"x": x, "top": int(top), "bottom": int(bottom), "center": float(center), "green": bool(is_green)})
            x += 8
        else: x += 2
    return candles

def features_from_candles(candles):
    if len(candles) < 10: return None
    centers = np.array([c["center"] for c in candles])
    prices = centers.max() - centers
    deltas = np.diff(prices)
    impulse = np.abs(deltas[-6:-1]).sum()
    exhaustion_ratio = abs(deltas[-1]) / (abs(deltas[-2]) + 1e-6) if len(deltas) >= 2 else 1
    ema20 = pd.Series(prices).ewm(span=20).mean().iloc[-1]
    dist_ema = prices[-1] - ema20
    rsi_series = calc_rsi(prices)
    rsi_val = rsi_series.iloc[-1] if not np.isnan(rsi_series.iloc[-1]) else 50
    last = candles[-1]
    body = abs(last["bottom"] - last["top"])
    prev_sizes = [abs(c["bottom"] - c["top"]) for c in candles[-6:-1]]
    avg_size = np.mean(prev_sizes) if prev_sizes else body
    is_doji = 1 if body < avg_size * 0.35 else 0
    fake_impulse = 0
    if len(candles) >= 2:
        if candles[-1]["green"] and candles[-2]["green"]: fake_impulse = 1
        if not candles[-1]["green"] and not candles[-2]["green"]: fake_impulse = 1
    return {"impulse": float(impulse), "exhaustion_ratio": float(exhaustion_ratio), "dist_ema": float(dist_ema), "rsi": float(rsi_val), "last_green": bool(candles[-1]["green"]), "n_candles": len(candles), "is_doji": int(is_doji), "fake_impulse": int(fake_impulse)}

def save_sample(photo_path, platform="pocket"):
    candles = extract_candles_from_screen(photo_path)
    feat = features_from_candles(candles)
    if not feat: return False
    feat["platform"] = platform
    feat["time"] = datetime.now().isoformat()
    feat["label"] = ""
    df = pd.DataFrame([feat])
    if os.path.exists(DATASET): df.to_csv(DATASET, mode='a', header=False, index=False)
    else: df.to_csv(DATASET, index=False)
    return True

def train_model():
    if not os.path.exists(DATASET): return {"msg": "Нет данных. Кидай фото через ОБУЧЕНИЕ"}
    df = pd.read_csv(DATASET)
    df = df[df["label"] != ""]
    if len(df) < 5: return {"msg": f"Мало размеченных фото: {len(df)}/20. После каждого фото пиши ВВЕРХ или ВНИЗ"}
    best = {"thr": 0.5, "acc": 0}
    for thr in [0.4, 0.5, 0.6, 0.7, 0.8]:
        pred = []
        for _, r in df.iterrows():
            if r["impulse"] > 30 and r["exhaustion_ratio"] < thr: pred.append("ВНИЗ" if r["dist_ema"] > 0 else "ВВЕРХ")
            else: pred.append("ЖДИ")
        acc = (np.array(pred) == df["label"].values).mean()
        if acc > best["acc"]: best = {"thr": thr, "acc": float(acc)}
    model = {"exhaustion_thr": best["thr"], "accuracy_on_train": best["acc"], "samples": len(df)}
    json.dump(model, open(MODEL_FILE, "w"))
    return model

def get_thr():
    if os.path.exists(MODEL_FILE):
        try: return json.load(open(MODEL_FILE)).get("exhaustion_thr", 0.5)
        except: return 0.5
    return 0.5

def analyze_otc_screenshot(photo_path):
    img = cv2.imread(photo_path)
    if img is None: return None, 0
    h, w = img.shape[:2]
    chart = img[int(h*0.18):int(h*0.65), 0:int(w*0.95)]
    if chart.size == 0: return None, 0
    hsv = cv2.cvtColor(chart, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35,50,50]), np.array([85,255,255]))
    red_mask1 = cv2.inRange(hsv, np.array([0,50,50]), np.array([10,255,255]))
    red_mask2 = cv2.inRange(hsv, np.array([160,50,50]), np.array([180,255,255]))
    candles_mask = cv2.bitwise_or(green_mask, cv2.bitwise_or(red_mask1, red_mask2))
    prices, greens, sizes = [], [], []
    for x in range(candles_mask.shape[1]-5, 0, -2):
        col = np.where(candles_mask[:, x] > 0)[0]
        if len(col) > 0:
            prices.append(chart.shape[0] - col.mean())
            greens.append(green_mask[:, x].max() > 0)
            sizes.append(col.max() - col.min())
    if len(prices) < 20: return None, 0
    prices, greens, sizes = prices[::-1], greens[::-1], sizes[::-1]
    if time.time() - sniper_state["last_signal_time"] < 120: return "СТОП, ПОДОЖДИ 2 МИН ПОСЛЕ СИГНАЛА", 0
    last_size = sizes[-1]
    avg_prev = np.mean(sizes[-7:-1]) if len(sizes) >= 7 else last_size
    is_doji = last_size < avg_prev * 0.4
    impulse_before = abs(prices[-3] - prices[-7]) if len(prices) >= 7 else 0
    fake = greens[-1] == greens[-2]
    if is_doji and fake and impulse_before > 15:
        return ("ВНИЗ" if greens[-1] else "ВВЕРХ"), 0
    deltas = np.diff(prices[-10:])
    exhaustion = abs(deltas[-1]) / (abs(deltas[-2]) + 1e-6) if len(deltas) >= 2 else 1
    thr = get_thr()
    if exhaustion < thr and impulse_before > 20: return ("ВНИЗ" if greens[-1] else "ВВЕРХ"), 0
    return None, 0

async def send_text(chat_id, text):
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

async def check_major_signal(pair, chat_id):
    if not is_market_open():
        await send_text(chat_id, "Реал закрыт до понедельника. Пиши OTC и кидай скрин.")
        return
    prices = await asyncio.to_thread(get_real_candles, pair)
    if not prices or len(prices) < 300:
        await send_text(chat_id, "Не смог взять свечи ни с ТВ ни с TwelveData")
        return
    rsi = calc_rsi(prices)
    ema200 = pd.Series(prices).ewm(span=200).mean()
    curr_rsi = rsi.iloc[-1]
    wins, total = 0, 0
    for i in range(200, len(prices)-5):
        if rsi.iloc[i] <= 30 and prices[i] < ema200.iloc[i]:
            total += 1
            if prices[i+3] > prices[i]: wins += 1
        elif rsi.iloc[i] >= 70 and prices[i] > ema200.iloc[i]:
            total += 1
            if prices[i+3] < prices[i]: wins += 1
    if total < 20:
        await send_text(chat_id, f"{pair}: мало статистики ({total}), жди")
        return
    wr = wins/total*100
    if wr < 58:
        await send_text(chat_id, f"{pair}: винрейт {wr:.0f}% - слабый, не захожу")
        return
    direction = "ВВЕРХ" if curr_rsi <= 30 else "ВНИЗ"
    await send_text(chat_id, f"МАЖОР {pair}\nRSI: {curr_rsi:.1f}\n{direction}\nВинрейт: {wr:.0f}% на {total} сделках\nЭкспирация 3м")

async def collect_majors_loop():
    print("Ночной сбор мажоров запущен...")
    while True:
        try:
            for pair in MAJORS:
                prices = await asyncio.to_thread(get_real_candles, pair)
                if not prices or len(prices) < 100: continue
                window = prices[-60:-3]
                future = prices[-3] - prices[-6]
                label = "ВВЕРХ" if future > 0 else "ВНИЗ"
                deltas = np.diff(window)
                impulse = np.abs(deltas[-6:-1]).sum()
                exhaustion_ratio = abs(deltas[-1]) / (abs(deltas[-2]) + 1e-6)
                ema20 = pd.Series(window).ewm(span=20).mean().iloc[-1]
                dist_ema = window[-1] - ema20
                rsi_val = calc_rsi(window).iloc[-1]
                if np.isnan(rsi_val): rsi_val = 50
                row = {"impulse": float(impulse), "exhaustion_ratio": float(exhaustion_ratio), "dist_ema": float(dist_ema), "rsi": float(rsi_val), "last_green": bool(window[-1] > window[-2]), "n_candles": len(window), "is_doji": 0, "fake_impulse": 0, "platform": pair, "time": datetime.now().isoformat(), "label": label}
                df = pd.DataFrame([row])
                if os.path.exists(DATASET): df.to_csv(DATASET, mode='a', header=False, index=False)
                else: df.to_csv(DATASET, index=False)
                print(f"Собрал {pair} -> {label}")
            m = train_model()
            print(f"Модель после сбора: {m}")
        except Exception as e:
            print("Ошибка сбора:", e)
        await asyncio.sleep(300)

async def analyze_all(chat_id):
    await send_text(chat_id, "Бро, прогоняю все 17 мажоров (ТВ + Twelve)... 20 сек")
    if not is_market_open():
        await send_text(chat_id, "Реал закрыт до понедельника. Пиши OTC и кидай скрин.")
        return
    async def fetch_and_calc(pair):
        prices = await asyncio.to_thread(get_real_candles, pair)
        if not prices or len(prices) < 300:
            return (pair, 0, 0, "нет свечей", 0)
        rsi = calc_rsi(prices)
        ema200 = pd.Series(prices).ewm(span=200).mean()
        curr_rsi = rsi.iloc[-1]
        if pd.isna(curr_rsi):
            curr_rsi = 50
        wins, total = 0, 0
        for i in range(200, len(prices)-5):
            if rsi.iloc[i] <= 30 and prices[i] < ema200.iloc[i]:
                total += 1
                if prices[i+3] > prices[i]: wins += 1
            elif rsi.iloc[i] >= 70 and prices[i] > ema200.iloc[i]:
                total += 1
                if prices[i+3] < prices[i]: wins += 1
        if total < 20:
            return (pair, 0, total, "мало статистики", float(curr_rsi))
        wr = wins/total*100
        direction = "ВВЕРХ" if curr_rsi <= 30 else "ВНИЗ"
        if 30 < curr_rsi < 70:
            direction = "ЖДИ"
        return (pair, wr, total, direction, float(curr_rsi))
    results = await asyncio.gather(*(fetch_and_calc(p) for p in MAJORS))
    results_sorted = sorted([r for r in results if r[1] > 0], key=lambda x: x[1], reverse=True)
    if not results_sorted:
        await send_text(chat_id, "Все 17 - ни ТВ ни Twelve не отдало. Проверь ключи")
        return
    best = results_sorted[0]
    text = "РЕЗУЛЬТАТ ПО 17 МАЖОРАМ:\n\n"
    for r in results:
        text += f"{r[0]}: {r[3]} | RSI {r[4]:.1f} | Винрейт {r[1]:.0f}% ({r[2]})\n"
    if best[1] >= 58 and best[3] != "ЖДИ":
        text += f"\nБРО, ЗАХОДИ В {best[0]} -> {best[3]}\nВинрейт {best[1]:.0f}% - это твой сетап. Экспирация 3м"
    else:
        text += f"\nБро, сейчас все в жди. Лучший {best[0]} с {best[1]:.0f}%, но RSI не дошел. Не заходи."
    await send_text(chat_id, text)

async def telegram_listener():
    offset = 0
    print("Бот слушает...")
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset": offset, "timeout": 25})
                data = r.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    if not chat_id: continue
                    text = msg.get("text", "").strip().upper()
                    if text == "/START":
                        await send_text(chat_id, "Привет\nEUR/USD - реал\nOTC - скрин\nОБУЧЕНИЕ - фото\nСИНХРОН - заходить со мной\nОБУЧИТЬ - обучить\nАНАЛИЗ - все 17 пар")
                    elif text == "/STOP":
                        sniper_state["waiting_photo"] = False
                        sniper_state["mode"] = None
                        await send_text(chat_id, "Остановлен")
                    elif text == "АНАЛИЗ":
                        asyncio.create_task(analyze_all(chat_id))
                    elif text in MAJORS:
                        await send_text(chat_id, f"Проверяю {text}...")
                        asyncio.create_task(check_major_signal(text, chat_id))
                    elif text == "OTC":
                        sniper_state["waiting_photo"] = True
                        sniper_state["mode"] = "otc"
                        sniper_state["chat_id"] = chat_id
                        await send_text(chat_id, "Кидай скрин EUR/USD-OTC 1м")
                    elif text == "ОБУЧЕНИЕ":
                        sniper_state["waiting_photo"] = True
                        sniper_state["mode"] = "train"
                        sniper_state["chat_id"] = chat_id
                        await send_text(chat_id, "Кидай фото 15м. После каждого фото напиши ВВЕРХ или ВНИЗ")
                    elif text == "СИНХРОН":
                        sniper_state["waiting_photo"] = True
                        sniper_state["mode"] = "sync"
                        sniper_state["chat_id"] = chat_id
                        await send_text(chat_id, "Режим СИНХРОН. Заходи на демо сам, кидай скрин В МОМЕНТ ВХОДА, потом напиши ВХОД ВНИЗ или ВХОД ВВЕРХ")
                    elif text.startswith("ВХОД"):
                        direction = text.replace("ВХОД", "").strip()
                        if direction not in ["ВВЕРХ", "ВНИЗ"]:
                            await send_text(chat_id, "Пиши так: ВХОД ВНИЗ")
                        else:
                            sniper_state["sync_time"] = time.time()
                            sniper_state["sync_dir"] = direction
                            sniper_state["sync_chat"] = chat_id
                            if os.path.exists("/tmp/screen.jpg"):
                                save_sample("/tmp/screen.jpg", platform="sync")
                                df = pd.read_csv(DATASET)
                                df.iloc[-1, df.columns.get_loc("label")] = direction
                                df.to_csv(DATASET, index=False)
                            await send_text(chat_id, f"Принял вход {direction}. Жду 70 сек, потом напишешь ПЛЮС или МИНУС")
                    elif text in ["ПЛЮС", "МИНУС"]:
                        if sniper_state["sync_dir"] is None:
                            await send_text(chat_id, "Сначала напиши ВХОД ВНИЗ")
                        else:
                            if text == "МИНУС":
                                df = pd.read_csv(DATASET)
                                df = df.drop(df.index[-1])
                                df.to_csv(DATASET, index=False)
                                await send_text(chat_id, "Понял, минус. Удалил, не буду так заходить")
                            else:
                                await send_text(chat_id, "Плюс! Записал твой вход, буду так же делать")
                                m = train_model()
                                await send_text(chat_id, f"Обучился: {m}")
                            sniper_state["sync_dir"] = None
                    elif text == "ОБУЧИТЬ":
                        model = train_model()
                        await send_text(chat_id, f"Готово: {model}")
                    elif text in ["ВВЕРХ", "ВНИЗ"]:
                        if os.path.exists(DATASET):
                            df = pd.read_csv(DATASET)
                            if len(df) > 0 and df.iloc[-1]["label"] == "":
                                df.iloc[-1, df.columns.get_loc("label")] = text
                                df.to_csv(DATASET, index=False)
                                await send_text(chat_id, f"Записал {text}. Кидай следующее фото или напиши ОБУЧИТЬ")
                            else:
                                await send_text(chat_id, "Сначала кидай фото")
                        else:
                            await send_text(chat_id, "Сначала кидай фото через ОБУЧЕНИЕ")
                    if "photo" in msg and sniper_state["waiting_photo"]:
                        file_id = msg["photo"][-1]["file_id"]
                        file_res = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file_id})
                        file_path = file_res.json()["result"]["file_path"]
                        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                        photo_data = await client.get(photo_url)
                        open("/tmp/screen.jpg", "wb").write(photo_data.content)
                        if sniper_state["mode"] == "train":
                            ok = save_sample("/tmp/screen.jpg", platform="pocket")
                            if ok: await send_text(chat_id, "Фото сохранил для обучения. Теперь напиши ВВЕРХ или ВНИЗ что было на следующей свече")
                            else: await send_text(chat_id, "Не смог вытащить свечи с фото. Скинь другой скрин 15м")
                        elif sniper_state["mode"] == "sync":
                            await send_text(chat_id, "Фото входа сохранил. Теперь заходи на демо и напиши ВХОД ВНИЗ или ВХОД ВВЕРХ")
                        else:
                            direction, rsi = analyze_otc_screenshot("/tmp/screen.jpg")
                            if direction and "СТОП" in direction: await send_text(chat_id, direction)
                            elif direction:
                                await send_text(chat_id, f"OTC СИГНАЛ\n{direction}\nЭкспирация 1-2м\nТолько демка")
                                sniper_state["last_signal_time"] = time.time()
                            else: await send_text(chat_id, "ЖДИ. Нет сетапа дожи+фейк")
                        sniper_state["waiting_photo"] = False
                        sniper_state["mode"] = None
            except Exception as e:
                print("Ошибка:", e)
                await asyncio.sleep(3)

async def sniper_loop():
    while True:
        await asyncio.sleep(10)
        if sniper_state["sync_dir"] and sniper_state["sync_chat"]:
            if time.time() - sniper_state["sync_time"] > 70:
                await send_text(sniper_state["sync_chat"], "Ну что там? Пиши ПЛЮС или МИНУС")
                sniper_state["sync_time"] = time.time() + 9999

async def main():
    await asyncio.gather(telegram_listener(), sniper_loop(), collect_majors_loop())

if __name__ == "__main__":
    asyncio.run(main())
