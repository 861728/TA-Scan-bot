"""scanner.py 검증 테스트 (목업 데이터 기반)."""

import sys
import os
sys.path.insert(0, ".")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")

import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

import config
import utils
from scanner import (
    build_sell_message,
    build_signal_message,
    check_sell_alerts,
    fetch_ohlcv,
    scan_all,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 헬퍼
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_ohlcv(closes, volumes=None, opens=None):
    """테스트용 OHLCV DataFrame."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    if opens is None:
        opens = [c * 0.99 for c in closes]
    highs = [max(o, c) * 1.01 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.98 for o, c in zip(opens, closes)]
    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    })


def make_crash_df():
    """베이스 6조건을 모두 충족하는 급락 + 반등 DataFrame.

    1) RSI < 25
    2) 전일 BB하단 이탈
    3) 당일 양봉
    4) 거래량 5일평균 1.5배+
    5) 20일 낙폭 -30% 이하
    6) 60MA 대비 -30% 이하
    """
    n = 80
    # 60일간 고가 유지 → 마지막 20일 급락 (-40%)
    high_price = 100000
    crash_end = high_price * 0.55  # -45% 급락

    closes = [high_price] * 60 + list(np.linspace(high_price * 0.95, crash_end, 19)) + [crash_end * 1.04]
    opens = [c * 1.001 for c in closes]  # 대부분 음봉
    volumes = [1_000_000] * 60 + [1_000_000] * 15 + [500_000] * 4 + [5_000_000]  # 마지막날 거래량 급증

    # 마지막날: 양봉 (시가 < 종가)
    opens[-1] = crash_end * 0.97
    closes[-1] = crash_end * 1.04

    # 전일: BB하단 이탈 유도 (이미 급락으로 충분)
    return make_ohlcv(closes, volumes, opens)


def setup_temp_trades(trades_data):
    """임시 trades.json 설정."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(trades_data, f)
    config.TRADES_PATH = path
    return path


def cleanup_temp(path):
    if os.path.exists(path):
        os.remove(path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 1: scan_all 기본 흐름
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scan_all_basic():
    print("=" * 50)
    print("1. scan_all 기본 흐름 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])

    # 목업: 3종목, 1개만 신호 발생
    mock_stocks = pd.DataFrame({
        "Code": ["005930", "000660", "999999"],
        "Name": ["삼성전자", "SK하이닉스", "테스트급락"],
        "Market": ["KOSPI"] * 3,
    })

    crash_df = make_crash_df()
    normal_df = make_ohlcv(list(np.linspace(50000, 55000, 80)))

    def mock_fetch(code, days=120):
        if code == "999999":
            return crash_df
        return normal_df

    with patch("scanner.get_all_stocks", return_value=mock_stocks), \
         patch("scanner.get_sector_map", return_value={}), \
         patch("scanner.fetch_ohlcv", side_effect=mock_fetch):

        signals = scan_all()

    print(f"신호 발생: {len(signals)}건")
    for s in signals:
        print(f"  {s['name']}({s['code']}) {s['signal']} ₩{s['price']:,.0f}")
        print(f"    RSI {s['rsi']} | 낙폭 {s['drop_20d']}% | 캔들 +{s['candle_pct']}% | 거래량 {s['vol_ratio']}x")

    # 정상 주가 2개는 신호 없어야 함
    normal_codes = [s["code"] for s in signals if s["code"] in ("005930", "000660")]
    assert len(normal_codes) == 0, f"정상 주가에서 신호 발생: {normal_codes}"
    print("✅ 정상 주가 → 신호 없음 확인")

    cleanup_temp(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 2: 슬롯 제한
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_slot_limit():
    print("=" * 50)
    print("2. 슬롯 제한 테스트")
    print("=" * 50)

    # 약신호 슬롯 2개 이미 사용 중
    existing = [
        {"code": "AAA", "name": "종목A", "price": 10000, "signal": "weak",
         "buy_date": datetime.now().strftime("%Y-%m-%d"), "fee": 30, "status": "holding"},
        {"code": "BBB", "name": "종목B", "price": 20000, "signal": "weak",
         "buy_date": datetime.now().strftime("%Y-%m-%d"), "fee": 60, "status": "holding"},
    ]
    tmp = setup_temp_trades(existing)

    mock_stocks = pd.DataFrame({
        "Code": ["111111", "222222"],
        "Name": ["급락1", "급락2"],
        "Market": ["KOSPI"] * 2,
    })
    crash_df = make_crash_df()

    # classify_signal이 "weak"을 반환하도록 강제
    with patch("scanner.get_all_stocks", return_value=mock_stocks), \
         patch("scanner.get_sector_map", return_value={}), \
         patch("scanner.fetch_ohlcv", return_value=crash_df), \
         patch("scanner.classify_signal", return_value="weak"):

        signals = scan_all()

    weak_signals = [s for s in signals if s["signal"] == "weak"]
    print(f"기존 약신호 보유: 2개 (슬롯 MAX={config.MAX_WEAK_SLOTS})")
    print(f"새 약신호 발생: {len(weak_signals)}건")
    assert len(weak_signals) == 0, f"슬롯 초과 약신호 발생: {len(weak_signals)}"
    print("✅ 약신호 슬롯 초과 차단 확인")

    cleanup_temp(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 3: build_signal_message
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_build_signal_message():
    print("=" * 50)
    print("3. build_signal_message 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])

    # 신호 없음
    msg_empty = build_signal_message([])
    print("[신호 없음 메시지]")
    print(msg_empty)
    assert "신호 없음" in msg_empty
    print("✅ 신호 없음 메시지 확인")
    print()

    # 강신호 + 약신호
    signals = [
        {"code": "005930", "name": "삼성전자", "signal": "strong",
         "price": 55000, "rsi": 18.5, "drop_20d": -42.1, "candle_pct": 3.5, "vol_ratio": 4.2},
        {"code": "000660", "name": "SK하이닉스", "signal": "weak",
         "price": 120000, "rsi": 23.1, "drop_20d": -31.5, "candle_pct": 2.3, "vol_ratio": 1.8},
    ]
    msg = build_signal_message(signals)
    print("[신호 있음 메시지]")
    print(msg)
    assert "🔥 강신호" in msg
    assert "⚡ 약신호" in msg
    assert "삼성전자" in msg
    assert "SK하이닉스" in msg
    print("✅ 강/약 신호 메시지 포맷 확인")

    cleanup_temp(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 4: check_sell_alerts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_sell_alerts():
    print("=" * 50)
    print("4. check_sell_alerts 테스트")
    print("=" * 50)

    today = datetime.now()

    # 약신호: 21일 전 매수 → 청산 대상
    # 강신호: 6일 전 매수, 수익률 -5% → 조기청산 대상
    # 약신호: 5일 전 매수 → 아직 아님
    trades = [
        {"code": "005930", "name": "삼성전자", "price": 50000, "signal": "weak",
         "buy_date": (today - timedelta(days=21)).strftime("%Y-%m-%d"),
         "fee": 150, "status": "holding"},
        {"code": "000660", "name": "SK하이닉스", "price": 150000, "signal": "strong",
         "buy_date": (today - timedelta(days=6)).strftime("%Y-%m-%d"),
         "fee": 450, "status": "holding"},
        {"code": "035720", "name": "카카오", "price": 40000, "signal": "weak",
         "buy_date": (today - timedelta(days=5)).strftime("%Y-%m-%d"),
         "fee": 120, "status": "holding"},
    ]
    tmp = setup_temp_trades(trades)

    # 강신호 5일 체크: 현재가 142500 → 수익률 -5%
    mock_df = make_ohlcv([142500] * 10)

    with patch("scanner.fetch_ohlcv", return_value=mock_df):
        alerts = check_sell_alerts()

    print(f"매도 알람: {len(alerts)}건")
    for a in alerts:
        print(f"  {a['name']}({a['code']}) | {a['reason']}")

    alert_codes = [a["code"] for a in alerts]

    # 삼성전자: 21일 → 약신호 청산
    assert "005930" in alert_codes, "삼성전자 약신호 20일 청산 누락"
    print("✅ 약신호 20일 청산 확인")

    # SK하이닉스: 6일 + 수익률 -5% → 조기청산
    assert "000660" in alert_codes, "SK하이닉스 강신호 조기청산 누락"
    hynix = [a for a in alerts if a["code"] == "000660"][0]
    assert "조기청산" in hynix["reason"]
    print("✅ 강신호 5일 조기청산 확인")

    # 카카오: 5일 → 아직 아님
    assert "035720" not in alert_codes, "카카오가 청산 대상이면 안 됨"
    print("✅ 미도래 종목 제외 확인")

    cleanup_temp(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 5: build_sell_message
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_build_sell_message():
    print("=" * 50)
    print("5. build_sell_message 테스트")
    print("=" * 50)

    # 빈 알람 → 빈 문자열
    msg_empty = build_sell_message([])
    assert msg_empty == "", f"빈 알람인데 메시지 생성됨: '{msg_empty}'"
    print("✅ 빈 알람 → 빈 문자열")

    alerts = [
        {"code": "005930", "name": "삼성전자", "price": 50000, "reason": "약신호 20일 청산"},
        {"code": "000660", "name": "SK하이닉스", "price": 150000, "reason": "강신호 5일 조기청산 (수익률 -5.0%)"},
    ]
    msg = build_sell_message(alerts)
    print("[매도 알람 메시지]")
    print(msg)
    assert "⏰ 매도 알람" in msg
    assert "삼성전자" in msg
    assert "SK하이닉스" in msg
    print("✅ 매도 알람 메시지 포맷 확인")
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 테스트 6: 엣지 케이스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_edge_cases():
    print("=" * 50)
    print("6. 엣지 케이스 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])

    # 데이터 부족 (30일만)
    short_df = make_ohlcv([50000] * 30)
    with patch("scanner.get_all_stocks", return_value=pd.DataFrame({
        "Code": ["TEST01"], "Name": ["짧은데이터"], "Market": ["KOSPI"]
    })), \
         patch("scanner.get_sector_map", return_value={}), \
         patch("scanner.fetch_ohlcv", return_value=short_df):

        signals = scan_all()
    assert len(signals) == 0
    print("✅ 데이터 부족(30일) → 신호 없음")

    # fetch 실패 (None 반환)
    with patch("scanner.get_all_stocks", return_value=pd.DataFrame({
        "Code": ["TEST02"], "Name": ["실패종목"], "Market": ["KOSPI"]
    })), \
         patch("scanner.get_sector_map", return_value={}), \
         patch("scanner.fetch_ohlcv", return_value=None):

        signals = scan_all()
    assert len(signals) == 0
    print("✅ fetch 실패(None) → 신호 없음")

    # 빈 종목 리스트
    with patch("scanner.get_all_stocks", return_value=pd.DataFrame(columns=["Code", "Name", "Market"])), \
         patch("scanner.get_sector_map", return_value={}):

        signals = scan_all()
    assert len(signals) == 0
    print("✅ 빈 종목 리스트 → 신호 없음")

    cleanup_temp(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    test_scan_all_basic()
    test_slot_limit()
    test_build_signal_message()
    test_sell_alerts()
    test_build_sell_message()
    test_edge_cases()
    print("=" * 50)
    print("🎉 scanner.py 모든 테스트 완료")
