from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from urllib import parse, request

from .trade_store import Trade, TradeStore


class TelegramHandler:
    """
    urllib 전용 Telegram 명령어 폴링 핸들러 (외부 라이브러리 미사용).

    지원 명령어:
        /buy SYMBOL PRICE  — 매수 기록 저장
        /positions         — 보유 포지션 조회
    """

    _SEP = "━━━━━━━━━━━━━━━"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        trade_store: TradeStore,
        track1_symbols: tuple[str, ...] | list[str] = (),
        track2_symbols: tuple[str, ...] | list[str] = (),
        poll_interval: int = 2,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.trade_store = trade_store
        self.track1_symbols: set[str] = set(track1_symbols)
        self.track2_symbols: set[str] = set(track2_symbols)
        self.poll_interval = poll_interval
        self._offset: int = 0
        self._running: bool = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """별도 daemon 스레드에서 polling 시작."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="tg-poll")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------ #
    # Polling loop                                                         #
    # ------------------------------------------------------------------ #

    def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = self._get_updates()
                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    try:
                        self._dispatch(upd)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def _get_updates(self) -> list[dict]:
        url = (
            f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            f"?offset={self._offset}&timeout=0"
        )
        req = request.Request(url)
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("result", [])

    # ------------------------------------------------------------------ #
    # Dispatch                                                             #
    # ------------------------------------------------------------------ #

    def _dispatch(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        # 등록된 chat_id에서 온 메시지만 처리
        if str(message.get("chat", {}).get("id", "")) != self.chat_id:
            return

        text: str = message.get("text", "").strip()
        if not text.startswith("/"):
            return

        # '/command@botname arg' 형태 처리
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()

        if cmd == "/buy":
            self._handle_buy(parts[1:])
        elif cmd == "/positions":
            self._handle_positions()

    # ------------------------------------------------------------------ #
    # Command handlers                                                     #
    # ------------------------------------------------------------------ #

    def _handle_buy(self, args: list[str]) -> None:
        if len(args) < 2:
            self._send("사용법: /buy SYMBOL PRICE\n예시: /buy NVDA 176.21")
            return

        symbol = args[0].upper()
        try:
            price = float(args[1].replace(",", ""))
        except ValueError:
            self._send(f"가격 형식 오류: '{args[1]}'\n예시: /buy NVDA 176.21")
            return

        if symbol in self.track1_symbols:
            track = 1
        elif symbol in self.track2_symbols:
            track = 2
        else:
            track = 1  # 미등록 종목은 트랙 1 기본값

        today = datetime.now().strftime("%Y-%m-%d")
        self.trade_store.add_trade(symbol, price, today, track)

        sell_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        track_label = "트랙 1 🔴" if track == 1 else "트랙 2 🟢"

        self._send("\n".join([
            "✅ 매수 기록 저장",
            self._SEP,
            f"📌 종목: {symbol} ({track_label})",
            f"💰 진입가: ${price:,.2f}",
            f"📅 진입일: {today}",
            f"📅 매도 권장일: {sell_date} (30일)",
        ]))

    def _handle_positions(self) -> None:
        trades = self.trade_store.get_open_trades()
        if not trades:
            self._send("현재 보유 포지션 없음")
            return

        today = datetime.now().date()
        lines = ["📋 보유 포지션", self._SEP]

        for i, trade in enumerate(trades, 1):
            track_emoji = "🔴" if trade.track == 1 else "🟢"
            entry_date = datetime.fromisoformat(trade.entry_date).date()
            days_held = (today - entry_date).days

            current = self._fetch_current_price(trade.symbol)
            lines.append(f"{i}. {trade.symbol} {track_emoji}")
            if current is not None:
                pnl = (current / trade.entry_price - 1) * 100
                sign = "+" if pnl >= 0 else ""
                lines.append(f"   진입가: ${trade.entry_price:,.2f} → 현재가: ${current:,.2f}")
                lines.append(f"   수익률: {sign}{pnl:.1f}% | D+{days_held}")
            else:
                lines.append(f"   진입가: ${trade.entry_price:,.2f} | D+{days_held}")

        self._send("\n".join(lines))

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _fetch_current_price(self, symbol: str) -> float | None:
        """yfinance optional import — providers.py 스타일 유지."""
        try:
            import yfinance as yf  # optional runtime dependency
            hist = yf.Ticker(symbol).history(period="2d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(url, data=data, method="POST")
        try:
            with request.urlopen(req, timeout=10) as resp:
                _ = resp.read()
        except Exception:
            pass
