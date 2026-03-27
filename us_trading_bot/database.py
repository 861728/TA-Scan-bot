"""
US Trading Bot - Database (SQLite)

positions: 현재 보유 포지션
trades:    청산 완료 내역
"""

import sqlite3
from datetime import datetime, date

from us_trading_bot.config import DB_PATH

_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL UNIQUE,
    entry_date  TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    rsi14       REAL,
    rsi5        REAL,
    bb_pct      REAL,
    drawdown    REAL,
    vol_ratio   REAL,
    created_at  TEXT    NOT NULL
)
"""

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT    NOT NULL,
    entry_date  TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    rsi14       REAL,
    rsi5        REAL,
    bb_pct      REAL,
    drawdown    REAL,
    vol_ratio   REAL,
    exit_date   TEXT    NOT NULL,
    exit_price  REAL    NOT NULL,
    exit_type   TEXT    NOT NULL,
    hold_days   INTEGER NOT NULL,
    return_pct  REAL    NOT NULL,
    created_at  TEXT    NOT NULL
)
"""


def _connect(db_path=None):
    return sqlite3.connect(db_path or DB_PATH)


def init_db(db_path=None):
    conn = _connect(db_path)
    conn.execute(_CREATE_POSITIONS)
    conn.execute(_CREATE_TRADES)
    conn.commit()
    conn.close()


def add_position(ticker, entry_date, entry_price, indicators, db_path=None):
    conn = _connect(db_path)
    conn.execute(
        """INSERT INTO positions
           (ticker, entry_date, entry_price, rsi14, rsi5, bb_pct, drawdown, vol_ratio, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            str(entry_date),
            entry_price,
            indicators.get("rsi14"),
            indicators.get("rsi5"),
            indicators.get("bb_pct"),
            indicators.get("drawdown"),
            indicators.get("vol_ratio"),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_positions(db_path=None):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM positions ORDER BY entry_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_position(ticker, db_path=None):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM positions WHERE ticker = ?", (ticker,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def remove_position(ticker, db_path=None):
    conn = _connect(db_path)
    cur = conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def add_trade(position, exit_date, exit_price, exit_type, db_path=None):
    entry_date = date.fromisoformat(str(position["entry_date"]))
    exit_dt = date.fromisoformat(str(exit_date))
    hold_days = (exit_dt - entry_date).days
    return_pct = round((exit_price - position["entry_price"]) / position["entry_price"] * 100, 2)

    conn = _connect(db_path)
    conn.execute(
        """INSERT INTO trades
           (ticker, entry_date, entry_price, rsi14, rsi5, bb_pct, drawdown, vol_ratio,
            exit_date, exit_price, exit_type, hold_days, return_pct, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            position["ticker"],
            str(position["entry_date"]),
            position["entry_price"],
            position.get("rsi14"),
            position.get("rsi5"),
            position.get("bb_pct"),
            position.get("drawdown"),
            position.get("vol_ratio"),
            str(exit_date),
            exit_price,
            exit_type,
            hold_days,
            return_pct,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return {"hold_days": hold_days, "return_pct": return_pct}


def get_trades(db_path=None):
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY exit_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]
