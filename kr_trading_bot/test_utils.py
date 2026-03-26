"""utils.py 검증 테스트 (모의 데이터 기반)."""

import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from utils import (
    calc_rsi,
    calc_bollinger,
    calc_ma,
    calc_volume_ratio,
    calc_drop_from_high,
    calc_candle_body_pct,
    filter_excluded_sectors,
    name_to_code,
    check_base_conditions,
    classify_signal,
)


def make_ohlcv(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    """테스트용 OHLCV DataFrame 생성."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    opens = [c * 0.99 for c in closes]  # 시가 = 종가의 99%
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.98 for c in closes]
    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    })


def test_indicators():
    """1. 기술적 지표 계산 테스트 (삼성전자 모의 데이터)."""
    print("=" * 50)
    print("1. 기술적 지표 계산 테스트")
    print("=" * 50)

    # 삼성전자 스타일: 80일 동안 60000→50000 하락 추세
    np.random.seed(42)
    base = np.linspace(60000, 50000, 80)
    noise = np.random.normal(0, 300, 80)
    closes = list(base + noise)
    volumes = list(np.random.randint(5_000_000, 20_000_000, 80).astype(float))

    df = make_ohlcv(closes, volumes)
    close = df["Close"]

    print(f"데이터: {len(df)}일, 현재가: ₩{close.iloc[-1]:,.0f}")
    print()

    # RSI
    rsi = calc_rsi(close)
    rsi_val = rsi.iloc[-1]
    print(f"RSI(14): {rsi_val:.1f}")
    assert 0 <= rsi_val <= 100, f"RSI 범위 오류: {rsi_val}"
    assert not pd.isna(rsi_val), "RSI가 NaN"
    print("  ✅ RSI 범위 정상 (0~100)")
    print()

    # 볼린저밴드
    mid, upper, lower, width = calc_bollinger(close)
    print(f"볼린저밴드:")
    print(f"  상단: ₩{upper.iloc[-1]:,.0f}")
    print(f"  중심: ₩{mid.iloc[-1]:,.0f}")
    print(f"  하단: ₩{lower.iloc[-1]:,.0f}")
    print(f"  BB폭: {width.iloc[-1]:.4f}")
    assert upper.iloc[-1] > mid.iloc[-1] > lower.iloc[-1], "BB 순서 오류"
    assert width.iloc[-1] > 0, "BB폭이 0 이하"
    print("  ✅ 상단 > 중심 > 하단, BB폭 > 0")
    print()

    # 20일 낙폭
    drop_20 = calc_drop_from_high(close, 20)
    drop_val = drop_20.iloc[-1]
    print(f"20일 고점 대비 낙폭: {drop_val:.1f}%")
    assert drop_val <= 0, "낙폭이 양수일 수 없음"
    print("  ✅ 낙폭 ≤ 0 정상")
    print()

    # 60일 이동평균 대비 괴리율
    ma60 = calc_ma(close, 60)
    gap = (close.iloc[-1] / ma60.iloc[-1] - 1) * 100
    print(f"60일 이동평균: ₩{ma60.iloc[-1]:,.0f}")
    print(f"현재가 괴리율: {gap:.1f}%")
    assert not pd.isna(gap), "괴리율 NaN"
    print("  ✅ 괴리율 계산 정상")
    print()

    # 거래량 5일평균 대비
    vol_ratio = calc_volume_ratio(df["Volume"], 5)
    vr_val = vol_ratio.iloc[-1]
    print(f"거래량 5일평균 대비: {vr_val:.2f}x")
    assert vr_val > 0, "거래량 비율이 0 이하"
    print("  ✅ 거래량 비율 > 0 정상")
    print()


def test_sector_filter():
    """2. 제외 업종 필터 테스트."""
    print("=" * 50)
    print("2. 제외 업종 필터 테스트")
    print("=" * 50)

    stocks = pd.DataFrame({
        "Code": ["005930", "000660", "068270", "051910"],
        "Name": ["삼성전자", "SK하이닉스", "셀트리온", "LG화학"],
        "Market": ["KOSPI"] * 4,
    })

    # 셀트리온=제약, LG화학=화학
    sector_map = {
        "005930": "반도체",
        "000660": "반도체",
        "068270": "제약",
        "051910": "화학",
    }

    filtered = filter_excluded_sectors(stocks, sector_map)

    print(f"필터 전: {len(stocks)}개 → 필터 후: {len(filtered)}개")
    print(f"남은 종목: {list(filtered['Name'])}")

    assert len(filtered) == 2, f"기대 2개, 실제 {len(filtered)}개"
    assert "삼성전자" in filtered["Name"].values
    assert "SK하이닉스" in filtered["Name"].values
    assert "셀트리온" not in filtered["Name"].values, "셀트리온(제약) 필터링 실패"
    assert "LG화학" not in filtered["Name"].values, "LG화학(화학) 필터링 실패"
    print("✅ 제외 업종 필터 통과")
    print()


def test_name_to_code():
    """3. name_to_code 테스트 (네트워크 불가 → 로직만 검증)."""
    print("=" * 50)
    print("3. name_to_code 로직 테스트")
    print("=" * 50)

    # _stock_cache를 직접 주입해서 테스트
    import utils
    utils._stock_cache = pd.DataFrame({
        "Code": ["005930", "000660", "035720"],
        "Name": ["삼성전자", "SK하이닉스", "카카오"],
        "Market": ["KOSPI", "KOSPI", "KOSPI"],
    })

    code1 = name_to_code("삼성전자")
    print(f"'삼성전자' → '{code1}'")
    assert code1 == "005930", f"기대 '005930', 실제 '{code1}'"
    print("  ✅ 삼성전자 매핑 통과")

    code2 = name_to_code("SK하이닉스")
    print(f"'SK하이닉스' → '{code2}'")
    assert code2 == "000660"
    print("  ✅ SK하이닉스 매핑 통과")

    code3 = name_to_code("없는종목")
    print(f"'없는종목' → {code3}")
    assert code3 is None, f"기대 None, 실제 '{code3}'"
    print("  ✅ 없는 종목 None 반환 통과")

    # 부분 매칭 테스트
    code4 = name_to_code("삼성")
    print(f"'삼성' (부분매칭) → '{code4}'")
    assert code4 == "005930"
    print("  ✅ 부분 매칭 통과")
    print()


def test_signal_classification():
    """4. 보너스: 신호 판별 로직 테스트."""
    print("=" * 50)
    print("4. 신호 판별 로직 테스트")
    print("=" * 50)

    # 베이스 조건 미충족 (정상 주가) → None
    normal_closes = list(np.linspace(50000, 55000, 80))
    df_normal = make_ohlcv(normal_closes)
    sig = classify_signal(df_normal)
    print(f"정상 주가 → 신호: {sig}")
    assert sig is None, "정상 주가에서 신호 발생하면 안 됨"
    print("  ✅ 정상 주가 → None 통과")

    # 급락 시나리오 (RSI < 25 유도)
    crash = list(np.linspace(60000, 60000, 40)) + list(np.linspace(59000, 38000, 40))
    # 마지막날 양봉: open < close
    vols = [5_000_000] * 75 + [30_000_000] * 5  # 마지막 5일 거래량 급증
    df_crash = make_ohlcv(crash, vols)
    # 마지막날 강제 양봉 (종가 > 시가)
    df_crash.loc[df_crash.index[-1], "Open"] = crash[-1] * 0.95
    df_crash.loc[df_crash.index[-1], "Close"] = crash[-1]

    base_ok = check_base_conditions(df_crash)
    print(f"급락 시나리오 베이스 조건: {base_ok}")

    rsi_val = calc_rsi(df_crash["Close"]).iloc[-1]
    _, _, lower, _ = calc_bollinger(df_crash["Close"])
    prev_close = df_crash["Close"].iloc[-2]
    prev_lower = lower.iloc[-2]
    print(f"  RSI: {rsi_val:.1f} (기준 < 25)")
    print(f"  전일종가: {prev_close:,.0f} vs BB하단: {prev_lower:,.0f} (이탈 여부: {prev_close < prev_lower})")
    print(f"  당일 양봉: {df_crash['Close'].iloc[-1] > df_crash['Open'].iloc[-1]}")
    print()


if __name__ == "__main__":
    test_indicators()
    test_sector_filter()
    test_name_to_code()
    test_signal_classification()
    print("=" * 50)
    print("🎉 모든 테스트 완료")
