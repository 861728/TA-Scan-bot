"""
US Trading Bot - Indicators

yfinance 데이터 다운로드 + 기술 지표 계산
- fetch_single(ticker): 단일 종목
- fetch_all(tickers):   배치 다운로드 (44개 한 번에)
"""

import yfinance as yf
import pandas as pd

from us_trading_bot.config import SYMBOLS, DATA_PERIOD


def _calc_rsi(delta, window):
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _compute_indicators(df):
    """단일 종목 DataFrame → 최신 지표 dict 반환. 데이터 부족 시 None."""
    if df is None or len(df) < 252:
        return None

    close = df["Close"]
    volume = df["Volume"]
    open_ = df["Open"]

    delta = close.diff()

    rsi14 = _calc_rsi(delta, 14)
    rsi5 = _calc_rsi(delta, 5)

    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    bb_pct = (close - bb_lower) / (bb_upper - bb_lower)

    high52w = close.rolling(252).max()
    drawdown = (close - high52w) / high52w * 100

    vol_ma20 = volume.rolling(20).mean()
    vol_ratio = volume / vol_ma20

    last = len(close) - 1
    if pd.isna(rsi14.iloc[last]):
        return None

    return {
        "rsi14": round(float(rsi14.iloc[last]), 2),
        "rsi5": round(float(rsi5.iloc[last]), 2),
        "bb_pct": round(float(bb_pct.iloc[last]), 4),
        "drawdown": round(float(drawdown.iloc[last]), 2),
        "vol_ratio": round(float(vol_ratio.iloc[last]), 2),
        "close": round(float(close.iloc[last]), 2),
        "open": round(float(open_.iloc[last]), 2),
    }


def fetch_single(ticker, period=None):
    """단일 종목 데이터 다운로드 + 지표 계산.

    Returns:
        dict | None: 지표 dict. 실패 시 None.
    """
    period = period or DATA_PERIOD
    try:
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    except Exception:
        return None

    if df.empty:
        return None

    # yf.download 단일 종목도 MultiIndex 반환할 수 있음
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel("Ticker", axis=1)

    return _compute_indicators(df)


def fetch_all(tickers=None, period=None):
    """배치 다운로드 후 전종목 지표 계산.

    Returns:
        dict: {ticker: indicators_dict, ...}  실패 종목은 제외.
    """
    tickers = tickers or SYMBOLS
    period = period or DATA_PERIOD

    try:
        raw = yf.download(tickers, period=period, auto_adjust=True,
                          group_by="ticker", progress=False, threads=True)
    except Exception:
        return {}

    if raw.empty:
        return {}

    results = {}
    for ticker in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[ticker].dropna(how="all")
            else:
                # 종목 1개만 남은 경우 MultiIndex 아님
                df = raw.copy()
            indicators = _compute_indicators(df)
            if indicators is not None:
                results[ticker] = indicators
        except (KeyError, Exception):
            continue

    return results
