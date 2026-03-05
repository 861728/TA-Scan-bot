from __future__ import annotations

import csv
import json
import os
from datetime import datetime as _dt
from typing import Callable
from urllib import parse, request


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout_seconds: int = 10,
        post: Callable[[str, bytes, int], None] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds
        self._post = post or self._default_post

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text}
        data = parse.urlencode(payload).encode("utf-8")
        self._post(url, data, self.timeout_seconds)

    @staticmethod
    def _default_post(url: str, data: bytes, timeout_seconds: int) -> None:
        req = request.Request(url=url, data=data, method="POST")
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            _ = resp.read()


class SafeNotifier:
    """Protect runtime loop from notifier exceptions."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def send(self, text: str) -> None:
        try:
            self.inner.send(text)
        except Exception:
            print(json.dumps({"level": "warning", "message": "notifier failed"}))


class CsvLogger:
    """강신호 알림을 CSV에 기록한다."""

    FIELDS = ["symbol", "timestamp", "grouped_score", "indicators"]

    def __init__(self, path: str) -> None:
        self.path = path
        if not os.path.exists(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=self.FIELDS).writeheader()

    def log(self, symbol: str, ts: _dt, score: int, indicators: str) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=self.FIELDS).writerow({
                "symbol": symbol,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
                "grouped_score": score,
                "indicators": indicators,
            })
