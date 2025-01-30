"""
auto_trader.py

- Upbit API 활용 (매수, 매도, 잔고, 시세 조회)
- SQLite DB 연동 (매매기록 저장)
- OpenAI API 활용 (투자판단 예시)
- 간단한 자동투자 로직(데이터 수집 → 분석 → 판단 → 매매 → 로그저장)
"""

import os
import time
import sqlite3
from datetime import datetime

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
# OpenAI 키 설정
openai.api_key = OPENAI_API_KEY


# -----------------------------------------------------------------------------
# 2. DB 초기화 및 매매 로그 저장 함수
# -----------------------------------------------------------------------------
def init_db(db_path="trade_log.db"):
    """
    SQLite DB 초기화. trade_log 테이블이 없으면 생성.
    """
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
    """
    매매 로그를 DB에 삽입
    """
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
    """
    현재가 조회
    """
    try:
        price = pyupbit.get_current_price(market)
        return price
    except Exception as e:
        print(f"[오류] 현재가 조회 실패: {e}")
        return None


def buy_coin(market: str, price: float, volume: float):
    """
    지정가 매수 예시
    market: 예) "KRW-BTC"
    price: 매수 단가
    volume: 매수 수량
    """
    try:
        order = upbit.buy_limit_order(market, price, volume)
        print("[매수 요청]", order)
        return order
    except Exception as e:
        print(f"[오류] 매수 실패: {e}")
        return None


def sell_coin(market: str, price: float, volume: float):
    """
    지정가 매도 예시
    """
    try:
        order = upbit.sell_limit_order(market, price, volume)
        print("[매도 요청]", order)
        return order
    except Exception as e:
        print(f"[오류] 매도 실패: {e}")
        return None


def get_balances():
    """
    잔고 조회
    """
    try:
        balances = upbit.get_balances()
        return balances
    except Exception as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return None


# -----------------------------------------------------------------------------
# 4. 과거 데이터 조회 & 간단한 분석 예시
# -----------------------------------------------------------------------------
def get_historical_data(market="KRW-BTC", interval="day", count=200):
    """
    과거 데이터 (OHLCV) 가져오기
    """
    df = pyupbit.get_ohlcv(market, interval=interval, count=count)
    return df


def simple_analysis(df: pd.DataFrame):
    """
    간단한 예시:
    - 5일 이동평균(ma5)
    - 20일 이동평균(ma20)
    - 이동평균 데드/골든크로스 여부 간단 체크
    """
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()

    # 마지막 row의 ma5, ma20
    last_ma5 = df["ma5"].iloc[-1]
    last_ma20 = df["ma20"].iloc[-1]

    # ma5 > ma20 이면 골든크로스(매수 시그널) 간단 예시
    if last_ma5 > last_ma20:
        return "buy_signal"
    else:
        return "sell_signal"


# -----------------------------------------------------------------------------
# 5. OpenAI API를 활용한 투자판단 보조 함수
# -----------------------------------------------------------------------------
def get_investment_opinion(data_summary: str):
    """
    data_summary(문자열)에 시장 요약 정보 등을 담아 모델에 전달.
    매수/매도/홀딩 중 어떤 것을 추천하는지 답변받는 예시.
    """
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
        answer = response.choices[0].message.content
        return answer
    except Exception as e:
        print("OpenAI API 호출 에러:", e)
        return None


# -----------------------------------------------------------------------------
# 6. 메인 로직 (주기적으로 실행하는 간단 예시)
# -----------------------------------------------------------------------------
def main():
    """
    - DB 연결
    - 주기적으로(예: while문) 시세 분석 → 매매(샘플) → 로그 저장
    """
    # DB 초기화
    conn = init_db("trade_log.db")

    market = "KRW-BTC"
    interval = "day"
    count = 30

    # 반복 예시 (Ctrl + C로 종료)
    while True:
        try:
            # 1) 데이터 수집
            df = get_historical_data(market, interval, count)
            current_price = get_current_price(market)
            if df is None or current_price is None:
                print("[경고] 데이터 수집 실패. 잠시 후 재시도.")
                time.sleep(5)
                continue

            # 2) 간단 분석
            signal = simple_analysis(df)  # "buy_signal" or "sell_signal"

            # 3) OpenAI API 의견 (간단 요약문 생성해서 넘김)
            # 예: 최근 종가 5개, ma5, ma20 등 텍스트로 정리
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

            # (AI 답변에서 단순 키워드로 매수/매도 판단 예시)
            # 실제로는 자연어 파싱, 정규표현식, 추가 검증 로직 필요
            if "매수" in ai_opinion or "buy" in ai_opinion.lower() or signal == "buy_signal":
                # 예시: 현재가에서 1% 아래 가격으로 지정가 매수 주문 (볼륨: 0.0001 BTC)
                buy_price = current_price * 0.99
                volume = 0.0001
                order = buy_coin(market, buy_price, volume)
                if order:
                    reason_text = f"AI 의견/이평 시그널: 매수. Reason: {ai_opinion}"
                    insert_trade_log(conn, "BUY", market, volume, buy_price, reason_text)

            elif "매도" in ai_opinion or "sell" in ai_opinion.lower() or signal == "sell_signal":
                # 예시: 현재가에서 1% 위 가격으로 지정가 매도 주문 (볼륨: 0.0001 BTC)
                sell_price = current_price * 1.01
                volume = 0.0001
                order = sell_coin(market, sell_price, volume)
                if order:
                    reason_text = f"AI 의견/이평 시그널: 매도. Reason: {ai_opinion}"
                    insert_trade_log(conn, "SELL", market, volume, sell_price, reason_text)

            # 다음 루프까지 대기
            time.sleep(10)

        except KeyboardInterrupt:
            print("\n사용자에 의해 종료됨.")
            break
        except Exception as e:
            print("[오류]", e)
            time.sleep(10)


if __name__ == "__main__":
    main()