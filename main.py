import time, random, pandas as pd
from datetime import datetime
import httpx

# --- ТВОИ НАСТРОЙКИ ---
BOT_TOKEN = "ТВОЙ_ТОКЕН"
CHANNEL_ID = "@ТВОЙ_КАНАЛ"

# Симуляция свечей, потом подключим твой API покета
def get_candles(n=500):
    # Тут ты подставишь реальные свечи с Pocket Option
    # Пока для теста генерим, но логика уже боевая
    return [random.uniform(1.0, 1.2) for _ in range(n)]

def rsi(prices, period=14):
    df = pd.Series(prices)
    delta = df.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_history(prices, curr_rsi):
    """Ищем исторические совпадения"""
    rsi_series = rsi(prices)
    similar = 0
    wins_up = 0
    wins_down = 0
    
    for i in range(50, len(prices)-10):
        if abs(rsi_series.iloc[i] - curr_rsi) < 2.5: # Нашли похожее RSI
            similar += 1
            # Что было дальше?
            future = prices[i+5] - prices[i]
            if future > 0: wins_up += 1
            else: wins_down += 1
    
    if similar == 0: return 50, 0
    win_rate = max(wins_up, wins_down) / similar * 100
    direction = "ВВЕРХ 🟢" if wins_up > wins_down else "ВНИЗ 🔴"
    return win_rate, direction, similar

def is_otc_manipulation(prices):
    """Фильтр от нарисованного графика"""
    last_10 = prices[-10:]
    volatility = (max(last_10) - min(last_10)) / max(last_10) * 100
    if volatility < 0.03: # Слишком ровный - крутят
        return True
    return False

async def send_signal(text):
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                          json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"})

async def main():
    print("БРОДЯГА PRO MAX ЗАПУЩЕН...")
    while True:
        try:
            prices = get_candles(500)
            curr_rsi = rsi(prices).iloc[-1]
            
            # Фильтр 1: ОТС крутилка
            if is_otc_manipulation(prices):
                print(f"{datetime.now()} - График крутят, пропуск")
                time.sleep(120)
                continue

            # Фильтр 2: Только сильные RSI зоны
            if curr_rsi > 58 or curr_rsi < 42:
                win_rate, hist_direction, similar_count = check_history(prices, curr_rsi)
                
                # Шлем только если история подтверждает >65%
                if win_rate >= 65 and similar_count >= 3:
                    msg = f"""
🔥 <b>БРОДЯГА PRO SIGNAL</b> 🔥

📊 Актив: ОТС (любой)
📈 RSI: {curr_rsi:.1f}
🧠 Исторических совпадений: {similar_count}
✅ Винрейт по истории: {win_rate:.0f}%
➡️ Направление: {hist_direction}

⏰ Время: {datetime.now().strftime('%H:%M:%S')}
⚠️ Уверенность: {win_rate:.0f}% - ЗАХОДИМ!

#PRO #OTC
                    """
                    await send_signal(msg)
                    print(f"SIGNAL SENT: {hist_direction} {win_rate}%")
                    time.sleep(900) # Пауза 15 мин после сигнала
                else:
                    print(f"RSI {curr_rsi:.1f} но история слабая {win_rate:.0f}% ({similar_count}) - пропуск")
            
            time.sleep(60) # Проверка каждую минуту
            
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(60)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
