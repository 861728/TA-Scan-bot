from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Trade:
    id: int
    symbol: str
    entry_price: float
    entry_date: str
    track: int
    status: str


class TradeStore:
    """SQLite 기반 매수 포지션 저장소."""

    def __init__(self, db_path: str = "trades.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT    NOT NULL,
                    entry_price REAL    NOT NULL,
                    entry_date  TEXT    NOT NULL,
                    track       INTEGER NOT NULL,
                    status      TEXT    DEFAULT 'open'
                )
                """
            )
            conn.commit()

    def add_trade(self, symbol: str, entry_price: float, entry_date: str, track: int) -> int:
        """신규 매수 저장. 생성된 row id 반환."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO trades (symbol, entry_price, entry_date, track) VALUES (?, ?, ?, ?)",
                (symbol, entry_price, entry_date, track),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def get_open_trades(self) -> list[Trade]:
        """status='open'인 포지션 전체 반환 (진입일 오름차순)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, symbol, entry_price, entry_date, track, status "
                "FROM trades WHERE status = 'open' ORDER BY entry_date"
            ).fetchall()
        return [Trade(*row) for row in rows]

    def close_trade(self, trade_id: int) -> None:
        """status를 'closed'로 업데이트."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE trades SET status = 'closed' WHERE id = ?", (trade_id,))
            conn.commit()

    def get_trades_due_today(self) -> list[Trade]:
        """진입일 기준 30일이 지난 open 포지션 반환."""
        today = datetime.utcnow().date()
        due: list[Trade] = []
        for trade in self.get_open_trades():
            entry = datetime.fromisoformat(trade.entry_date).date()
            if today >= entry + timedelta(days=30):
                due.append(trade)
        return due

    def get_portfolio_summary(self) -> list[Trade]:
        """open 포지션 전체 반환 (진입가, 진입일, 트랙 포함). get_open_trades 의 alias."""
        return self.get_open_trades()
