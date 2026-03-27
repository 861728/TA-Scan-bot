"""
US Trading Bot - Scanner

진입/청산 조건 스캔
- scan_entries(): 44개 전종목 진입 신호 스캔
- scan_exits():   보유 포지션 청산 신호 스캔
"""

from datetime import date

from us_trading_bot.config import (
    ENTRY_RSI14_MAX, ENTRY_RSI5_MAX, ENTRY_BB_PCT_MAX,
    ENTRY_DRAWDOWN_MAX, ENTRY_VOL_RATIO_MIN,
    EXIT_RSI5_MIN, EXIT_RSI14_MIN, EXIT_BB_PCT_MIN,
    EXIT_MAX_HOLD_DAYS,
)
from us_trading_bot.indicators import fetch_all, fetch_single
from us_trading_bot.database import get_positions


def _check_entry(ind):
    """진입 조건 6개 전부 만족 여부"""
    return (
        ind["rsi14"] < ENTRY_RSI14_MAX
        and ind["rsi5"] < ENTRY_RSI5_MAX
        and ind["bb_pct"] < ENTRY_BB_PCT_MAX
        and ind["drawdown"] < ENTRY_DRAWDOWN_MAX
        and ind["vol_ratio"] > ENTRY_VOL_RATIO_MIN
        and ind["close"] > ind["open"]
    )


def _check_exit_peak(ind):
    """고점 청산 조건"""
    return (
        ind["rsi5"] >= EXIT_RSI5_MIN
        and ind["rsi14"] >= EXIT_RSI14_MIN
        and ind["bb_pct"] >= EXIT_BB_PCT_MIN
    )


def scan_entries(db_path=None):
    """44개 전종목 스캔 → 진입 조건 충족 종목 반환.

    이미 positions에 있는 종목은 제외.

    Returns:
        list[dict]: 진입 신호 종목 리스트
    """
    all_indicators = fetch_all()
    if not all_indicators:
        return []

    held = {p["ticker"] for p in get_positions(db_path)}

    signals = []
    for ticker, ind in all_indicators.items():
        if ticker in held:
            continue
        if _check_entry(ind):
            signals.append({
                "ticker": ticker,
                "rsi14": ind["rsi14"],
                "rsi5": ind["rsi5"],
                "bb_pct": ind["bb_pct"],
                "drawdown": ind["drawdown"],
                "vol_ratio": ind["vol_ratio"],
                "close": ind["close"],
            })

    return signals


def scan_exits(db_path=None, today=None):
    """보유 포지션 청산 신호 스캔.

    Returns:
        list[dict]: 청산 대상 리스트 (exit_type: 'peak' | 'forced')
    """
    positions = get_positions(db_path)
    if not positions:
        return []

    today = today or date.today()
    tickers = [p["ticker"] for p in positions]

    all_indicators = fetch_all(tickers)

    signals = []
    for pos in positions:
        ticker = pos["ticker"]
        entry_dt = date.fromisoformat(str(pos["entry_date"]))
        hold_days = (today - entry_dt).days
        entry_price = pos["entry_price"]

        ind = all_indicators.get(ticker)

        # 강제 청산 (지표 없어도 판단 가능)
        if hold_days >= EXIT_MAX_HOLD_DAYS:
            close = ind["close"] if ind else entry_price
            return_pct = round((close - entry_price) / entry_price * 100, 2)
            signals.append({
                "ticker": ticker,
                "exit_type": "forced",
                "close": close,
                "hold_days": hold_days,
                "return_pct": return_pct,
            })
            continue

        # 고점 신호 (지표 필요)
        if ind is None:
            continue

        if _check_exit_peak(ind):
            return_pct = round((ind["close"] - entry_price) / entry_price * 100, 2)
            signals.append({
                "ticker": ticker,
                "exit_type": "peak",
                "close": ind["close"],
                "hold_days": hold_days,
                "return_pct": return_pct,
            })

    return signals
