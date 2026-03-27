"""database.py 단위 테스트"""

import os
import tempfile
import pytest
import sqlite3
from us_trading_bot.database import (
    init_db, add_position, get_positions, get_position,
    remove_position, add_trade, get_trades,
)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


SAMPLE_INDICATORS = {
    "rsi14": 28.3,
    "rsi5": 14.2,
    "bb_pct": 0.032,
    "drawdown": -24.1,
    "vol_ratio": 1.85,
}


# ── init_db ──────────────────────────────────────────────

def test_init_db_creates_tables(db_path):
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    names = {t[0] for t in tables}
    assert "positions" in names
    assert "trades" in names


def test_init_db_idempotent(db_path):
    # 두 번 호출해도 에러 없음
    init_db(db_path)
    init_db(db_path)


# ── add_position / get ───────────────────────────────────

def test_add_and_get_position(db_path):
    add_position("TSLA", "2026-03-20", 234.50, SAMPLE_INDICATORS, db_path)
    pos = get_position("TSLA", db_path)
    assert pos is not None
    assert pos["ticker"] == "TSLA"
    assert pos["entry_price"] == 234.50
    assert pos["rsi14"] == 28.3
    assert pos["bb_pct"] == 0.032


def test_get_positions_empty(db_path):
    assert get_positions(db_path) == []


def test_get_position_not_found(db_path):
    assert get_position("FAKE", db_path) is None


def test_get_positions_multiple(db_path):
    add_position("TSLA", "2026-03-20", 234.50, SAMPLE_INDICATORS, db_path)
    add_position("NVDA", "2026-03-21", 120.00, SAMPLE_INDICATORS, db_path)
    positions = get_positions(db_path)
    assert len(positions) == 2
    # entry_date 순 정렬
    assert positions[0]["ticker"] == "TSLA"
    assert positions[1]["ticker"] == "NVDA"


def test_duplicate_ticker_raises(db_path):
    add_position("TSLA", "2026-03-20", 234.50, SAMPLE_INDICATORS, db_path)
    with pytest.raises(sqlite3.IntegrityError):
        add_position("TSLA", "2026-03-21", 240.00, SAMPLE_INDICATORS, db_path)


# ── remove_position ──────────────────────────────────────

def test_remove_position(db_path):
    add_position("TSLA", "2026-03-20", 234.50, SAMPLE_INDICATORS, db_path)
    deleted = remove_position("TSLA", db_path)
    assert deleted == 1
    assert get_position("TSLA", db_path) is None


def test_remove_nonexistent(db_path):
    deleted = remove_position("FAKE", db_path)
    assert deleted == 0


# ── add_trade / get_trades ───────────────────────────────

def test_add_trade_calculates_fields(db_path):
    add_position("TSLA", "2026-03-01", 200.00, SAMPLE_INDICATORS, db_path)
    pos = get_position("TSLA", db_path)
    result = add_trade(pos, "2026-03-25", 250.00, "high_signal", db_path)
    assert result["hold_days"] == 24
    assert result["return_pct"] == 25.0


def test_add_trade_negative_return(db_path):
    add_position("AMD", "2026-03-01", 100.00, SAMPLE_INDICATORS, db_path)
    pos = get_position("AMD", db_path)
    result = add_trade(pos, "2026-03-10", 90.00, "forced", db_path)
    assert result["hold_days"] == 9
    assert result["return_pct"] == -10.0


def test_get_trades_empty(db_path):
    assert get_trades(db_path) == []


def test_get_trades_ordered_by_exit_desc(db_path):
    add_position("TSLA", "2026-03-01", 200.00, SAMPLE_INDICATORS, db_path)
    pos1 = get_position("TSLA", db_path)
    add_trade(pos1, "2026-03-10", 220.00, "high_signal", db_path)
    remove_position("TSLA", db_path)

    add_position("NVDA", "2026-03-05", 100.00, SAMPLE_INDICATORS, db_path)
    pos2 = get_position("NVDA", db_path)
    add_trade(pos2, "2026-03-20", 130.00, "forced", db_path)

    trades = get_trades(db_path)
    assert len(trades) == 2
    # exit_date DESC
    assert trades[0]["ticker"] == "NVDA"
    assert trades[1]["ticker"] == "TSLA"


# ── 엣지 케이스: indicators 일부 누락 ────────────────────

def test_partial_indicators(db_path):
    partial = {"rsi14": 30.0}  # rsi5, bb_pct 등 없음
    add_position("MU", "2026-03-20", 80.00, partial, db_path)
    pos = get_position("MU", db_path)
    assert pos["rsi14"] == 30.0
    assert pos["rsi5"] is None
    assert pos["bb_pct"] is None


# ── 엣지 케이스: 첫 실행 (DB 파일 없음) ──────────────────

def test_fresh_db_file():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # 파일 삭제 → 첫 실행 시뮬레이션
    assert not os.path.exists(path)
    init_db(path)
    assert os.path.exists(path)
    assert get_positions(path) == []
    os.unlink(path)
