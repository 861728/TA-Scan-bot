from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from urllib import request as _urllib_request
from typing import Protocol

from .alert_engine import AlertDecision
from .data_layer import normalize_timestamp
from .indicator_engine import IndicatorResult, SignalSummary


class AIProvider(Protocol):
    name: str

    def generate(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class AIInterpretation:
    regime: str
    confidence: int
    summary: str
    risks: list[str]
    provider: str


@dataclass(frozen=True)
class AIInvocation:
    called: bool
    reason: str
    result: AIInterpretation | None


class AIUsageLimiter:
    def __init__(self, per_symbol: int = 3, global_daily: int = 20) -> None:
        self.per_symbol = per_symbol
        self.global_daily = global_daily
        self._sym: dict[tuple[str, date], int] = {}
        self._global: dict[date, int] = {}

    def allow(self, symbol: str, now: datetime) -> tuple[bool, str]:
        day = normalize_timestamp(now).date()
        if self._sym.get((symbol, day), 0) >= self.per_symbol:
            return False, "symbol daily limit"
        if self._global.get(day, 0) >= self.global_daily:
            return False, "global daily limit"
        return True, "ok"

    def consume(self, symbol: str, now: datetime) -> None:
        day = normalize_timestamp(now).date()
        self._sym[(symbol, day)] = self._sym.get((symbol, day), 0) + 1
        self._global[day] = self._global.get(day, 0) + 1


class ClaudeProvider:
    """Anthropic Claude provider via Messages API (stdlib only, no SDK needed)."""

    name = "claude"
    _API_URL = "https://api.anthropic.com/v1/messages"
    _MODEL = "claude-sonnet-4-6"
    _SYSTEM = (
        "You are a quantitative trading signal interpreter. "
        "Given numeric indicator data, return ONLY a JSON object with keys: "
        "regime (string), confidence (int 0-100), summary (string, Korean), risks (list of ≤3 Korean strings). "
        "No markdown, no explanation — pure JSON only."
    )

    def __init__(self, api_key: str, timeout: int = 20) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def generate(self, prompt: str) -> str:
        body = json.dumps({
            "model": self._MODEL,
            "max_tokens": 256,
            "system": self._SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = _urllib_request.Request(
            self._API_URL,
            data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with _urllib_request.urlopen(req, timeout=self._timeout) as resp:
            payload = json.loads(resp.read())
        return payload["content"][0]["text"]


class RuleBasedProvider:
    name = "rule_based"

    def generate(self, prompt: str) -> str:
        _ = prompt
        return json.dumps(
            {
                "regime": "reversal_watch",
                "confidence": 58,
                "summary": "수치 신호가 바닥권 반전 가능성을 시사합니다.",
                "risks": ["변동성 확대", "저점 재이탈 가능성"],
            },
            ensure_ascii=False,
        )


class AIInterpreter:
    def __init__(self, provider: AIProvider, limiter: AIUsageLimiter) -> None:
        self.provider = provider
        self.limiter = limiter

    def maybe_call(
        self,
        symbol: str,
        timeframe: str,
        summary: SignalSummary,
        results: list[IndicatorResult],
        decision: AlertDecision,
        now: datetime | None = None,
    ) -> AIInvocation:
        ts = normalize_timestamp(now or datetime.now())
        if not decision.should_send:
            return AIInvocation(False, "alert suppressed", None)
        if not summary.should_call_ai:
            return AIInvocation(False, "ai threshold unmet", None)

        allowed, reason = self.limiter.allow(symbol, ts)
        if not allowed:
            return AIInvocation(False, reason, None)

        prompt = self._build_prompt(symbol, timeframe, summary, results)
        payload = json.loads(self.provider.generate(prompt))
        conf = int(payload["confidence"])
        if conf < 0 or conf > 100:
            raise ValueError("confidence out of range")

        self.limiter.consume(symbol, ts)
        return AIInvocation(
            called=True,
            reason="ok",
            result=AIInterpretation(
                regime=str(payload["regime"]),
                confidence=conf,
                summary=str(payload["summary"]),
                risks=[str(x) for x in payload.get("risks", [])][:3],
                provider=self.provider.name,
            ),
        )

    @staticmethod
    def _build_prompt(symbol: str, timeframe: str, summary: SignalSummary, results: list[IndicatorResult]) -> str:
        return json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "score": summary.total_score,
                "direction": summary.strongest_signal.value,
                "results": [
                    {
                        "indicator": r.indicator,
                        "signal": r.signal.value,
                        "score": r.score,
                        "evidence": r.evidence,
                        "raw_values": r.raw_values,
                    }
                    for r in results
                ],
                "constraints": ["numeric evidence only", "no guarantee language"],
            },
            ensure_ascii=False,
        )
