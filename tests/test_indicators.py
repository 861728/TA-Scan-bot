"""indicators.py 단위 테스트

네트워크 필요 테스트: @pytest.mark.network  (기본 스킵, --run-network 옵션으로 실행)
로컬 로직 테스트: 합성 데이터 + mock으로 검증
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from us_trading_bot.indicators import fetch_single, fetch_all, _compute_indicators, _calc_rsi


# ── 합성 데이터 헬퍼 ────────────────────────────────────

def _make_df(n=300, seed=42):
    np.random.seed(seed)
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "Close": prices,
        "Open": prices - np.random.uniform(0, 1, n),
        "Volume": np.random.uniform(1e6, 5e6, n),
    })


# ── _calc_rsi 단위 테스트 ───────────────────────────────

def test_calc_rsi_range():
    np.random.seed(1)
    close = pd.Series(100 + np.cumsum(np.random.randn(100) * 0.5))
    delta = close.diff()
    rsi = _calc_rsi(delta, 14)
    valid = rsi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_calc_rsi_monotonic_up():
    """단조 증가 → RSI 100에 가까움"""
    close = pd.Series(range(1, 101), dtype=float)
    delta = close.diff()
    rsi = _calc_rsi(delta, 14)
    assert rsi.iloc[-1] == 100.0


def test_calc_rsi_monotonic_down():
    """단조 감소 → RSI 0에 가까움"""
    close = pd.Series(list(range(100, 0, -1)), dtype=float)
    delta = close.diff()
    rsi = _calc_rsi(delta, 14)
    assert rsi.iloc[-1] == 0.0


# ── _compute_indicators ─────────────────────────────────

def test_compute_indicators_none_input():
    assert _compute_indicators(None) is None


def test_compute_indicators_short_data():
    df = _make_df(n=100)
    assert _compute_indicators(df) is None


def test_compute_indicators_valid():
    df = _make_df(n=300)
    result = _compute_indicators(df)
    assert result is not None
    expected_keys = {"rsi14", "rsi5", "bb_pct", "drawdown", "vol_ratio", "close", "open"}
    assert set(result.keys()) == expected_keys


def test_compute_indicators_rsi_range():
    df = _make_df(n=300)
    result = _compute_indicators(df)
    assert 0 <= result["rsi14"] <= 100
    assert 0 <= result["rsi5"] <= 100


def test_compute_indicators_drawdown_nonpositive():
    df = _make_df(n=300)
    result = _compute_indicators(df)
    assert result["drawdown"] <= 0


def test_compute_indicators_vol_ratio_positive():
    df = _make_df(n=300)
    result = _compute_indicators(df)
    assert result["vol_ratio"] > 0


def test_compute_indicators_close_matches_last():
    df = _make_df(n=300)
    result = _compute_indicators(df)
    assert result["close"] == round(float(df["Close"].iloc[-1]), 2)


# ── fetch_single (mock) ─────────────────────────────────

def test_fetch_single_with_mock():
    df = _make_df(n=300)
    with patch("us_trading_bot.indicators.yf.download", return_value=df):
        result = fetch_single("FAKE")
    assert result is not None
    assert "rsi14" in result


def test_fetch_single_empty_df():
    with patch("us_trading_bot.indicators.yf.download", return_value=pd.DataFrame()):
        result = fetch_single("FAKE")
    assert result is None


def test_fetch_single_exception():
    with patch("us_trading_bot.indicators.yf.download", side_effect=Exception("fail")):
        result = fetch_single("FAKE")
    assert result is None


def test_fetch_single_multiindex():
    """yfinance가 MultiIndex 컬럼을 반환하는 경우"""
    df = _make_df(n=300)
    mi = pd.MultiIndex.from_tuples(
        [(col, "TSLA") for col in df.columns], names=["Price", "Ticker"]
    )
    df_mi = df.copy()
    df_mi.columns = mi
    with patch("us_trading_bot.indicators.yf.download", return_value=df_mi):
        result = fetch_single("TSLA")
    assert result is not None


# ── fetch_all (mock) ─────────────────────────────────────

def test_fetch_all_with_mock():
    df_a = _make_df(n=300, seed=1)
    df_b = _make_df(n=300, seed=2)
    # 배치 다운로드: MultiIndex (ticker, price)
    combined = pd.concat(
        {"AAPL": df_a, "MSFT": df_b}, axis=1
    )
    with patch("us_trading_bot.indicators.yf.download", return_value=combined):
        results = fetch_all(["AAPL", "MSFT"])
    assert "AAPL" in results
    assert "MSFT" in results


def test_fetch_all_skips_bad_ticker():
    df_a = _make_df(n=300, seed=1)
    df_b = _make_df(n=50, seed=2)  # 데이터 부족
    combined = pd.concat(
        {"AAPL": df_a, "BAD": df_b}, axis=1
    )
    with patch("us_trading_bot.indicators.yf.download", return_value=combined):
        results = fetch_all(["AAPL", "BAD"])
    assert "AAPL" in results
    assert "BAD" not in results


def test_fetch_all_empty():
    results = fetch_all([], period="2y")
    assert results == {}


def test_fetch_all_download_exception():
    with patch("us_trading_bot.indicators.yf.download", side_effect=Exception("net")):
        results = fetch_all(["AAPL"])
    assert results == {}


# ── 네트워크 테스트 (--run-network 옵션) ─────────────────

@pytest.mark.network
def test_live_fetch_single():
    result = fetch_single("AAPL", period="2y")
    assert result is not None
    assert 0 <= result["rsi14"] <= 100


@pytest.mark.network
def test_live_fetch_all():
    results = fetch_all(["AAPL", "MSFT", "TSLA"], period="2y")
    assert len(results) > 0
