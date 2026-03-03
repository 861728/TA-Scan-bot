from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
import ast
import os
import time
from typing import Callable

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from .ai_layer import AIInterpreter, AIUsageLimiter, ClaudeProvider, RuleBasedProvider
from .alert_engine import AlertEngine
from .data_layer import Bar, DataCache, DataLayer
from .indicator_engine import IndicatorEngine, IndicatorGroup
from .indicators import default_phase2_indicators
from .monitoring import RuntimeMetrics, RuntimeSnapshot
from .providers import KRWConverter
from .recovery import FetchRecovery
from .runtime import Notifier, ScanRuntimeConfig, ScannerRuntime


@dataclass(frozen=True)
class ScanAppConfig:
    symbols: list[str]
    timeframe: str
    interval_seconds: int
    cache_dir: str
    score_threshold: int
    ai_call_threshold: int
    min_s_hits_for_ai: int
    cooldown_minutes: int
    strengthen_delta: int
    ai_per_symbol_daily: int
    ai_global_daily: int
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    anthropic_api_key: str | None = None
    min_volume_multiple: float = 1.5
    fetch_delay_seconds: float = 0.5

    @staticmethod
    def from_toml(path: str | Path) -> "ScanAppConfig":
        payload = _load_toml_compat(Path(path))

        runtime = payload.get("runtime", {})
        scoring = payload.get("scoring", {})
        alerts = payload.get("alerts", {})
        ai = payload.get("ai", {})
        telegram = payload.get("telegram", {})

        return ScanAppConfig(
            symbols=list(runtime.get("symbols", ["AAPL"])),
            timeframe=str(runtime.get("timeframe", "15m")),
            interval_seconds=int(runtime.get("interval_seconds", 600)),
            cache_dir=str(runtime.get("cache_dir", "data/cache")),
            score_threshold=int(scoring.get("score_threshold", 5)),
            ai_call_threshold=int(scoring.get("ai_call_threshold", 6)),
            min_s_hits_for_ai=int(scoring.get("min_s_hits_for_ai", 2)),
            cooldown_minutes=int(alerts.get("cooldown_minutes", 120)),
            strengthen_delta=int(alerts.get("strengthen_delta", 3)),
            ai_per_symbol_daily=int(ai.get("per_symbol_daily", 3)),
            ai_global_daily=int(ai.get("global_daily", 20)),
            telegram_bot_token=_none_if_blank(telegram.get("bot_token")),
            telegram_chat_id=_none_if_blank(telegram.get("chat_id")),
            anthropic_api_key=_none_if_blank(ai.get("anthropic_api_key")) or _none_if_blank(os.environ.get("ANTHROPIC_API_KEY")),
            min_volume_multiple=float(scoring.get("min_volume_multiple", 1.5)),
            fetch_delay_seconds=float(runtime.get("fetch_delay_seconds", 0.5)),
        )


_ET = ZoneInfo("America/New_York")


def _is_us_market_hours(utc_now: datetime) -> bool:
    et = utc_now.astimezone(_ET)
    if et.weekday() >= 5:
        return False
    t = et.time()
    return dtime(9, 30) <= t < dtime(16, 0)


def _none_if_blank(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _load_toml_compat(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")

    try:
        import tomllib  # type: ignore

        return tomllib.loads(text)
    except ModuleNotFoundError:
        return _parse_toml_minimal(text)


def _parse_toml_minimal(text: str) -> dict:
    out: dict[str, dict[str, object]] = {}
    section = "root"
    out[section] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip()
        try:
            parsed = ast.literal_eval(val)
        except Exception:
            parsed = val.strip('"').strip("'")
        out[section][key] = parsed
    return out


class ConsoleNotifier:
    def send(self, text: str) -> None:
        print(text)


class ScanApplication:
    def __init__(self, config: ScanAppConfig, notifier: Notifier | None = None) -> None:
        self.config = config
        self.notifier = notifier or ConsoleNotifier()
        self._heartbeat_date: date | None = None

        self.metrics = RuntimeMetrics()

        cache = DataCache(config.cache_dir)
        self.runtime = ScannerRuntime(
            cache=cache,
            data_layer=DataLayer(cache),
            recovery=FetchRecovery(cache),
            indicator_engine=IndicatorEngine(
                indicators=default_phase2_indicators(),
                score_threshold=config.score_threshold,
                ai_call_threshold=config.ai_call_threshold,
                min_s_hits_for_ai=config.min_s_hits_for_ai,
                s_tier_names={"wvf_spike", "volume_capitulation", "obv_divergence"},
                min_volume_multiple=config.min_volume_multiple,
                groups=[
                    IndicatorGroup("oversold_momentum",
                        frozenset({"triple_stoch_rsi", "composite_oscillator", "rsi_sma200", "bb_stochastic", "ks_reversal"}),
                        cap=2),
                    IndicatorGroup("money_flow",
                        frozenset({"mfi", "cmf", "adline_divergence", "nvi_pvi"}),
                        cap=2),
                    IndicatorGroup("divergence",
                        frozenset({"macd_divergence", "obv_divergence", "macd_obv_divergence"}),
                        cap=4),
                    IndicatorGroup("volume_structure",
                        frozenset({"volume_capitulation", "vpt", "wvf_spike"}),
                        cap=5),
                    IndicatorGroup("trend_structure",
                        frozenset({"ichimoku_rsi_obv", "fibonacci_618_support"}),
                        cap=2),
                ],
            ),
            alert_engine=AlertEngine(
                cooldown_minutes=config.cooldown_minutes,
                strengthened_delta=config.strengthen_delta,
            ),
            ai_interpreter=AIInterpreter(
                provider=ClaudeProvider(config.anthropic_api_key) if config.anthropic_api_key else RuleBasedProvider(),
                limiter=AIUsageLimiter(
                    per_symbol=config.ai_per_symbol_daily,
                    global_daily=config.ai_global_daily,
                ),
            ),
            notifier=self.notifier,
            metrics=self.metrics,
            krw_converter=KRWConverter(),
        )

    def run_once(self, fetcher: Callable[[str, str], list[Bar]]) -> None:
        now = datetime.utcnow()
        alerts_sent = 0
        weak_signals: list[tuple[str, int, str]] = []
        for i, symbol in enumerate(self.config.symbols):
            result = self.runtime.run_cycle(
                config=ScanRuntimeConfig(symbol=symbol, timeframe=self.config.timeframe),
                fetcher=fetcher,
                now=now,
            )
            if result.alert_decision.should_send:
                alerts_sent += 1
            elif result.summary.grouped_score >= 1 and not result.summary.should_alert:
                weak_signals.append((
                    symbol,
                    result.summary.grouped_score,
                    result.summary.strongest_signal.name,
                ))
            if i < len(self.config.symbols) - 1:
                time.sleep(self.config.fetch_delay_seconds)
        self._maybe_send_heartbeat(now, alerts_sent, weak_signals)

    _DIR_KR = {"BULLISH": "매수", "BEARISH": "매도", "NEUTRAL": "중립"}

    def _maybe_send_heartbeat(
        self, utc_now: datetime, alerts_sent: int, weak_signals: list[tuple[str, int, str]]
    ) -> None:
        if not _is_us_market_hours(utc_now):
            return
        today_et = utc_now.astimezone(_ET).date()
        if self._heartbeat_date == today_et:
            return
        self._heartbeat_date = today_et
        if alerts_sent == 0:
            msg = (
                f"[M7 바닥 스캐너] 개장 스캔 완료\n"
                f"{len(self.config.symbols)}개 종목 이상 없음"
            )
            self.notifier.send(msg)
        if weak_signals:
            sorted_ws = sorted(weak_signals, key=lambda x: x[1], reverse=True)
            lines = [f"[M7 바닥 스캐너] 약신호 종목 ({len(sorted_ws)}개)"]
            for sym, score, dir_name in sorted_ws:
                dir_kr = self._DIR_KR.get(dir_name, dir_name)
                lines.append(f"{sym}  {dir_kr}  {score}점")
            self.notifier.send("\n".join(lines))

    def run_forever(self, fetcher: Callable[[str, str], list[Bar]]) -> None:
        while True:
            self.run_once(fetcher)
            time.sleep(self.config.interval_seconds)

    def get_metrics_snapshot(self) -> RuntimeSnapshot:
        return self.metrics.snapshot()
