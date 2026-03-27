"""scanner.py 단위 테스트 — mock으로 indicators/database 대체"""

import os
import tempfile
import pytest
from datetime import date
from unittest.mock import patch

from us_trading_bot.scanner import scan_entries, scan_exits, _check_entry, _check_exit_peak
from us_trading_bot.database import init_db, add_position, get_position


# ── fixtures ─────────────────────────────────────────────

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def _entry_hit():
    """진입 조건 전부 만족하는 지표"""
    return {
        "rsi14": 25.0, "rsi5": 12.0, "bb_pct": 0.02,
        "drawdown": -25.0, "vol_ratio": 2.0,
        "close": 105.0, "open": 100.0,
    }


def _entry_miss_rsi14():
    ind = _entry_hit()
    ind["rsi14"] = 35.0  # RSI14 > 31
    return ind


def _entry_miss_candle():
    ind = _entry_hit()
    ind["close"] = 99.0  # 음봉 (close < open)
    return ind


def _exit_peak_hit():
    """고점 청산 조건 만족"""
    return {
        "rsi14": 75.0, "rsi5": 85.0, "bb_pct": 0.95,
        "drawdown": -2.0, "vol_ratio": 1.1,
        "close": 300.0, "open": 295.0,
    }


def _exit_no_peak():
    return {
        "rsi14": 50.0, "rsi5": 50.0, "bb_pct": 0.50,
        "drawdown": -10.0, "vol_ratio": 1.0,
        "close": 250.0, "open": 248.0,
    }


SAMPLE_IND = {
    "rsi14": 28.0, "rsi5": 14.0, "bb_pct": 0.03,
    "drawdown": -22.0, "vol_ratio": 1.5,
}


# ── _check_entry ─────────────────────────────────────────

def test_check_entry_all_met():
    assert _check_entry(_entry_hit()) is True


def test_check_entry_rsi14_fail():
    assert _check_entry(_entry_miss_rsi14()) is False


def test_check_entry_rsi5_fail():
    ind = _entry_hit()
    ind["rsi5"] = 20.0
    assert _check_entry(ind) is False


def test_check_entry_bb_fail():
    ind = _entry_hit()
    ind["bb_pct"] = 0.10
    assert _check_entry(ind) is False


def test_check_entry_drawdown_fail():
    ind = _entry_hit()
    ind["drawdown"] = -15.0
    assert _check_entry(ind) is False


def test_check_entry_vol_fail():
    ind = _entry_hit()
    ind["vol_ratio"] = 1.0
    assert _check_entry(ind) is False


def test_check_entry_candle_fail():
    assert _check_entry(_entry_miss_candle()) is False


def test_check_entry_boundary_rsi14():
    """RSI14 == 31 → 조건 미충족 (< 31)"""
    ind = _entry_hit()
    ind["rsi14"] = 31.0
    assert _check_entry(ind) is False


# ── _check_exit_peak ─────────────────────────────────────

def test_check_exit_peak_all_met():
    assert _check_exit_peak(_exit_peak_hit()) is True


def test_check_exit_peak_rsi5_fail():
    ind = _exit_peak_hit()
    ind["rsi5"] = 75.0
    assert _check_exit_peak(ind) is False


def test_check_exit_peak_rsi14_fail():
    ind = _exit_peak_hit()
    ind["rsi14"] = 65.0
    assert _check_exit_peak(ind) is False


def test_check_exit_peak_bb_fail():
    ind = _exit_peak_hit()
    ind["bb_pct"] = 0.85
    assert _check_exit_peak(ind) is False


def test_check_exit_peak_boundary():
    """경계값 정확히 만족"""
    ind = {"rsi5": 80.0, "rsi14": 70.0, "bb_pct": 0.90,
           "drawdown": 0, "vol_ratio": 1, "close": 100, "open": 99}
    assert _check_exit_peak(ind) is True


# ── scan_entries ─────────────────────────────────────────

def test_scan_entries_returns_signals(db_path):
    mock_data = {"TSLA": _entry_hit(), "NVDA": _entry_miss_rsi14()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_entries(db_path)
    assert len(signals) == 1
    assert signals[0]["ticker"] == "TSLA"
    assert signals[0]["close"] == 105.0


def test_scan_entries_excludes_held(db_path):
    add_position("TSLA", "2026-03-01", 100.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _entry_hit(), "AMD": _entry_hit()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_entries(db_path)
    tickers = [s["ticker"] for s in signals]
    assert "TSLA" not in tickers
    assert "AMD" in tickers


def test_scan_entries_none_indicators(db_path):
    with patch("us_trading_bot.scanner.fetch_all", return_value={}):
        signals = scan_entries(db_path)
    assert signals == []


def test_scan_entries_all_fail(db_path):
    mock_data = {"TSLA": _entry_miss_rsi14(), "AMD": _entry_miss_candle()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_entries(db_path)
    assert signals == []


# ── scan_exits ───────────────────────────────────────────

def test_scan_exits_peak_signal(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _exit_peak_hit()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 20))
    assert len(signals) == 1
    assert signals[0]["exit_type"] == "peak"
    assert signals[0]["hold_days"] == 19
    assert signals[0]["return_pct"] == 50.0  # (300-200)/200*100


def test_scan_exits_forced(db_path):
    add_position("TSLA", "2026-01-01", 200.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _exit_no_peak()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert len(signals) == 1
    assert signals[0]["exit_type"] == "forced"
    assert signals[0]["hold_days"] == 83
    assert signals[0]["close"] == 250.0


def test_scan_exits_forced_no_indicators(db_path):
    """지표 다운로드 실패해도 강제 청산은 발동"""
    add_position("TSLA", "2026-01-01", 200.0, SAMPLE_IND, db_path)
    with patch("us_trading_bot.scanner.fetch_all", return_value={}):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert len(signals) == 1
    assert signals[0]["exit_type"] == "forced"
    assert signals[0]["close"] == 200.0  # fallback to entry_price


def test_scan_exits_no_positions(db_path):
    signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert signals == []


def test_scan_exits_no_signal(db_path):
    add_position("TSLA", "2026-03-20", 200.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _exit_no_peak()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert signals == []


def test_scan_exits_mixed(db_path):
    """하나는 고점, 하나는 강제, 하나는 해당없음"""
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    add_position("AMD", "2025-12-01", 100.0, SAMPLE_IND, db_path)
    add_position("NVDA", "2026-03-20", 150.0, SAMPLE_IND, db_path)
    mock_data = {
        "TSLA": _exit_peak_hit(),
        "AMD": _exit_no_peak(),
        "NVDA": _exit_no_peak(),
    }
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    types = {s["ticker"]: s["exit_type"] for s in signals}
    assert types["TSLA"] == "peak"
    assert types["AMD"] == "forced"  # 114일
    assert "NVDA" not in types


def test_scan_exits_indicator_missing_skip(db_path):
    """지표 없고 80일 미만 → 스킵"""
    add_position("TSLA", "2026-03-20", 200.0, SAMPLE_IND, db_path)
    with patch("us_trading_bot.scanner.fetch_all", return_value={}):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert signals == []


def test_scan_exits_forced_boundary(db_path):
    """정확히 80일 → 강제 청산 발동"""
    add_position("TSLA", "2026-01-04", 200.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _exit_no_peak()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert len(signals) == 1
    assert signals[0]["hold_days"] == 80
    assert signals[0]["exit_type"] == "forced"


def test_scan_exits_79days_no_signal(db_path):
    """79일 → 강제 청산 아직 안됨"""
    add_position("TSLA", "2026-01-05", 200.0, SAMPLE_IND, db_path)
    mock_data = {"TSLA": _exit_no_peak()}
    with patch("us_trading_bot.scanner.fetch_all", return_value=mock_data):
        signals = scan_exits(db_path, today=date(2026, 3, 25))
    assert signals == []
