# auto_trader.py

import os
import time
import sqlite3
from datetime import datetime

import schedule  # <= 새로 추가
import pyupbit
import openai
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

# -----------------------------------------------------------------------------
# 1. 환경변수에서 API 키 로드
# -----------------------------------------------------------------------------
UPBIT_ACCESS_KEY = os.getenv("UPBIT_ACCESS_KEY")
UPBIT_SECRET_KEY = os.getenv("UPBIT_SECRET_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# pyupbit 객체 생성
upbit = pyupbit.Upbit(UPBIT_ACCESS_KEY, UPBIT_SECRET_KEY)
openai.api_key = OPENAI_API_KEY

# -----------------------------------------------------------------------------
# 2. DB 초기화 및 매매 로그 저장 함수
# -----------------------------------------------------------------------------
def init_db(db_path="trade_log.db"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime TEXT,
            action TEXT,
            market TEXT,
            volume REAL,
            price REAL,
            reason TEXT
        )
    """)
    conn.commit()
    return conn

def insert_trade_log(conn, action, market, volume, price, reason):
    cur = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO trade_log (datetime, action, market, volume, price, reason)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (now, action, market, volume, price, reason))
    conn.commit()

# -----------------------------------------------------------------------------
# 3. Upbit API 함수들 (시세 조회, 매수, 매도)
# -----------------------------------------------------------------------------
def get_current_price(market: str = "KRW-BTC"):
    try:
        return pyupbit.get_current_price(market)
    except Exception as e:
        print(f"[오류] 현재가 조회 실패: {e}")
        return None

def buy_coin(market: str, price: float, volume: float):
    try:
        order = upbit.buy_limit_order(market, price, volume)
        print("[매수 요청]", order)
        return order
    except Exception as e:
        print(f"[오류] 매수 실패: {e}")
        return None

def sell_coin(market: str, price: float, volume: float):
    try:
        order = upbit.sell_limit_order(market, price, volume)
        print("[매도 요청]", order)
        return order
    except Exception as e:
        print(f"[오류] 매도 실패: {e}")
        return None

def get_balances():
    try:
        return upbit.get_balances()
    except Exception as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return None

# -----------------------------------------------------------------------------
# 4. 과거 데이터 조회 & 간단한 분석 예시
# -----------------------------------------------------------------------------
def get_historical_data(market="KRW-BTC", interval="day", count=200):
    return pyupbit.get_ohlcv(market, interval=interval, count=count)

def simple_analysis(df: pd.DataFrame):
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()

    last_ma5 = df["ma5"].iloc[-1]
    last_ma20 = df["ma20"].iloc[-1]

    if last_ma5 > last_ma20:
        return "buy_signal"
    else:
        return "sell_signal"

# -----------------------------------------------------------------------------
# 5. OpenAI API를 활용한 투자판단 보조 함수
# -----------------------------------------------------------------------------
def get_investment_opinion(data_summary: str):
    prompt = f"""
    다음은 비트코인 시장 데이터 요약입니다:
    {data_summary}

    - 최근 지표를 바탕으로, 현재 시점에서 매수/매도/홀딩 중 어느 것을 추천하고,
      그 이유는 무엇인가?
    """
    client = OpenAI()
    try:
        response = client.chat.completions.create(
            model="o1-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print("OpenAI API 호출 에러:", e)
        return None

# -----------------------------------------------------------------------------
# 5-1. 호가단위 보정 함수
# -----------------------------------------------------------------------------
def adjust_price_to_tick(price: float):
    if price >= 2_000_000:
        return round(price / 1000) * 1000
    elif price >= 1_000_000:
        return round(price / 500) * 500
    elif price >= 500_000:
        return round(price / 100) * 100
    elif price >= 100_000:
        return round(price / 50) * 50
    elif price >= 10_000:
        return round(price / 10) * 10
    elif price >= 1_000:
        return round(price / 5) * 5
    else:
        return round(price)

# -----------------------------------------------------------------------------
# 6. "한 번" 거래 실행하는 함수 (중요)
# -----------------------------------------------------------------------------
def trade_once(market="KRW-BTC", interval="day", count=30):
    """
    스케줄러에서 호출할 함수: 매매 로직을 한 번만 실행
    """
    try:
        conn = init_db("trade_log.db")

        df = get_historical_data(market, interval, count)
        current_price = get_current_price(market)
        if df is None or current_price is None:
            print("[경고] 데이터 수집 실패, trade_once 종료")
            return

        signal = simple_analysis(df)

        recent_closes = df["close"].tail(5).tolist()
        last_ma5 = round(df["ma5"].iloc[-1], 2)
        last_ma20 = round(df["ma20"].iloc[-1], 2)

        summary_text = f"""
        최근 종가 5개: {recent_closes}
        5일 이평: {last_ma5}
        20일 이평: {last_ma20}
        분석 시그널: {signal}
        현재가: {current_price}
        """
        ai_opinion = get_investment_opinion(summary_text)
        if ai_opinion is None:
            ai_opinion = "AI 의견 조회 실패"

        print("\n----- AI Opinion -----\n", ai_opinion, "\n----------------------\n")

        # 간단한 매수/매도 로직
        if "매수" in ai_opinion or "buy" in ai_opinion.lower() or signal == "buy_signal":
            raw_buy_price = current_price * 0.99
            buy_price = adjust_price_to_tick(raw_buy_price)
            volume = 0.0001

            order = buy_coin(market, buy_price, volume)
            if order:
                reason_text = f"AI 의견/이평 시그널: 매수. Reason: {ai_opinion}"
                insert_trade_log(conn, "BUY", market, volume, buy_price, reason_text)

        elif "매도" in ai_opinion or "sell" in ai_opinion.lower() or signal == "sell_signal":
            raw_sell_price = current_price * 1.01
            sell_price = adjust_price_to_tick(raw_sell_price)
            volume = 0.0001

            order = sell_coin(market, sell_price, volume)
            if order:
                reason_text = f"AI 의견/이평 시그널: 매도. Reason: {ai_opinion}"
                insert_trade_log(conn, "SELL", market, volume, sell_price, reason_text)

    except Exception as e:
        print("[오류 in trade_once]", e)

# -----------------------------------------------------------------------------
# 7. schedule 라이브러리를 이용해서 9시, 14시, 20시에 trade_once 실행
# -----------------------------------------------------------------------------
def main():
    """
    schedule 라이브러리를 이용해 매일 09:00, 14:00, 20:00에
    trade_once를 자동으로 실행하는 예시
    """
    # "KRW-BTC"를 대상, interval="day", count=30
    schedule.every().day.at("09:00").do(trade_once, "KRW-BTC", "day", 30)
    schedule.every().day.at("14:00").do(trade_once, "KRW-BTC", "day", 30)
    schedule.every().day.at("20:00").do(trade_once, "KRW-BTC", "day", 30)
    trade_once()
    print("Scheduler started! Running pending jobs... (Ctrl+C to stop)")

    while True:
        # 스케줄된 작업(run_pending)들을 체크해서, 실행 시간이 되면 수행
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()