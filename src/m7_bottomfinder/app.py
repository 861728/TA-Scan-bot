from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import ast
import os
import time
from typing import Callable

import pytz
import schedule

from .ai_layer import AIInterpreter, AIUsageLimiter, ClaudeProvider, RuleBasedProvider
from .alert_engine import AlertEngine
from .data_layer import Bar, DataCache, DataLayer
from .indicator_engine import IndicatorEngine
from .indicators import default_phase2_indicators
from .monitoring import RuntimeMetrics, RuntimeSnapshot
from .providers import KRWConverter
from .recovery import FetchRecovery
from .runtime import Notifier, ScanRuntimeConfig, ScannerRuntime
from .trade_store import Trade, TradeStore


@dataclass(frozen=True)
class ScanAppConfig:
    symbols: list[str]
    timeframe: str
    interval_seconds: int
    cache_dir: str
    track1_threshold: int
    track2_threshold: int
    ai_call_threshold: int
    min_s_hits_for_ai: int
    cooldown_minutes: int
    strengthen_delta: int
    ai_per_symbol_daily: int
    ai_global_daily: int
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    anthropic_api_key: str | None = None
    db_path: str = "trades.db"
    high_risk_symbols: tuple[str, ...] = field(default_factory=tuple)
    low_risk_symbols: tuple[str, ...] = field(default_factory=tuple)
    track1_symbols: tuple[str, ...] = field(default_factory=tuple)
    track2_symbols: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def from_toml(path: str | Path) -> "ScanAppConfig":
        payload = _load_toml_compat(Path(path))

        runtime = payload.get("runtime", {})
        scoring = payload.get("scoring", {})
        alerts = payload.get("alerts", {})
        ai = payload.get("ai", {})
        telegram = payload.get("telegram", {})
        symbols_cfg = payload.get("symbols", {})

        return ScanAppConfig(
            symbols=list(runtime.get("symbols", ["AAPL"])),
            timeframe=str(runtime.get("timeframe", "15m")),
            interval_seconds=int(runtime.get("interval_seconds", 600)),
            cache_dir=str(runtime.get("cache_dir", "data/cache")),
            track1_threshold=int(scoring.get("track1_threshold", 4)),
            track2_threshold=int(scoring.get("track2_threshold", 5)),
            ai_call_threshold=int(scoring.get("ai_call_threshold", 6)),
            min_s_hits_for_ai=int(scoring.get("min_s_hits_for_ai", 2)),
            cooldown_minutes=int(alerts.get("cooldown_minutes", 120)),
            strengthen_delta=int(alerts.get("strengthen_delta", 3)),
            ai_per_symbol_daily=int(ai.get("per_symbol_daily", 3)),
            ai_global_daily=int(ai.get("global_daily", 20)),
            telegram_bot_token=_none_if_blank(telegram.get("bot_token")),
            telegram_chat_id=_none_if_blank(telegram.get("chat_id")),
            anthropic_api_key=_none_if_blank(ai.get("anthropic_api_key")) or _none_if_blank(os.environ.get("ANTHROPIC_API_KEY")),
            db_path=str(telegram.get("db_path", "trades.db")),
            high_risk_symbols=tuple(symbols_cfg.get("high_risk", [])),
            low_risk_symbols=tuple(symbols_cfg.get("low_risk", [])),
            track1_symbols=tuple(symbols_cfg.get("track1_symbols", ["NVDA", "MRVL", "CRWD", "ZS", "ON"])),
            track2_symbols=tuple(symbols_cfg.get("track2_symbols", ["MU", "LRCX", "NFLX", "KLAC"])),
        )


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
        self.trade_store = TradeStore(config.db_path)

        self.metrics = RuntimeMetrics()

        cache = DataCache(config.cache_dir)
        self.runtime = ScannerRuntime(
            cache=cache,
            data_layer=DataLayer(cache),
            recovery=FetchRecovery(cache),
            indicator_engine=IndicatorEngine(
                indicators=default_phase2_indicators(),
                track1_threshold=config.track1_threshold,
                track2_threshold=config.track2_threshold,
                ai_call_threshold=config.ai_call_threshold,
                min_s_hits_for_ai=config.min_s_hits_for_ai,
                s_tier_names={"wvf_spike", "volume_capitulation", "obv_divergence"},
                track1_symbols=list(config.track1_symbols),
                track2_symbols=list(config.track2_symbols),
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

    def run_once(self, fetcher: Callable[[str, str], list[Bar]]) -> list[str]:
        """Run a full scan cycle and send daily summary. Returns list of alerted symbols."""
        now = datetime.utcnow()
        today_kst = datetime.now(pytz.timezone("Asia/Seoul")).date()

        # ① D-7 ~ D-day 매도 알람 (해당 종목 있을 때만, 개별 발송)
        for trade in self.trade_store.get_trades_due_soon():
            bars = fetcher(trade.symbol, self.config.timeframe)
            current = bars[-1].close if bars else None
            self.notifier.send(self._build_sell_soon_alert(trade, current, today_kst))

        # ② 종목 스캔 (개별 알람 발송 없음 — run_cycle에서 notifier 미사용)
        high_risk_set = set(self.config.high_risk_symbols)
        low_risk_set = set(self.config.low_risk_symbols)
        # (symbol, track, score, last_price, condition_detail)
        alerted_info: list[tuple[str, int, int, float | None, str]] = []

        for symbol in self.config.symbols:
            if symbol in high_risk_set:
                risk_tier = "high"
            elif symbol in low_risk_set:
                risk_tier = "low"
            else:
                risk_tier = "default"

            result = self.runtime.run_cycle(
                config=ScanRuntimeConfig(symbol=symbol, timeframe=self.config.timeframe, risk_tier=risk_tier),
                fetcher=fetcher,
                now=now,
            )
            if result.alert_decision.should_send:
                cached = self.runtime.cache.load(symbol, self.config.timeframe)
                price = cached[-1].close if cached else None
                alerted_info.append((symbol, result.summary.track, result.summary.total_score, price, result.condition_detail))

        # ③ 포트폴리오 현재가 수집 (캐시 우선, 없으면 fetcher)
        portfolio = self.trade_store.get_portfolio_summary()
        portfolio_prices: dict[str, float | None] = {}
        for trade in portfolio:
            cached = self.runtime.cache.load(trade.symbol, self.config.timeframe)
            if cached:
                portfolio_prices[trade.symbol] = cached[-1].close
            else:
                bars = fetcher(trade.symbol, self.config.timeframe)
                portfolio_prices[trade.symbol] = bars[-1].close if bars else None

        # ④ 일일 요약 단일 발송
        self.notifier.send(self._build_daily_message(alerted_info, portfolio, portfolio_prices, today_kst))
        return [info[0] for info in alerted_info]

    @staticmethod
    def _build_sell_soon_alert(trade: Trade, current: float | None, today: date) -> str:
        """D-7 ~ D-day 매도 알람 한 줄 메시지."""
        entry_date = datetime.fromisoformat(trade.entry_date).date()
        sell_date = entry_date + timedelta(days=30)
        days_remaining = (sell_date - today).days

        if current is not None:
            pnl = (current / trade.entry_price - 1) * 100
            sign = "+" if pnl >= 0 else ""
            price_str = f" ${trade.entry_price:,.2f} → ${current:,.2f} ({sign}{pnl:.1f}%)"
        else:
            price_str = f" ${trade.entry_price:,.2f}"

        if days_remaining <= 0:
            return f"⏰ {trade.symbol} 오늘 매도일{price_str} | 오늘 청산 권장"
        return f"⏰ {trade.symbol} 매도 D-{days_remaining}{price_str} | 매도일 {sell_date.strftime('%Y-%m-%d')}"

    @staticmethod
    def _build_daily_message(
        alerted_info: list[tuple[str, int, int, float | None, str]],
        portfolio: list[Trade],
        portfolio_prices: dict[str, float | None],
        today: date,
    ) -> str:
        """일일 요약 메시지 (신호 + 포트폴리오 통합)."""
        SEP = "━━━━━━━━━━━━━━━"
        lines = [f"📅 {today.strftime('%Y-%m-%d')} 스캔 결과", SEP]

        # 신호 섹션
        if alerted_info:
            lines.append("⚡ 신호")
            for symbol, track, score, price, condition_detail in alerted_info:
                track_label = "⚡고수익" if track == 1 else "🛡️안전"
                target_pct = "+20%" if track == 1 else "+10%"
                price_str = f"${price:,.2f}" if price is not None else "N/A"
                lines.append(f"• {symbol} {track_label} ({score}점) | {price_str} | {target_pct} | 30일")
                if condition_detail:
                    lines.append(f"  {condition_detail}")
        else:
            lines.append("⚡ 신호: 없음")

        lines.append("")

        # 포지션 섹션
        if portfolio:
            lines.append("💼 보유 포지션")
            for trade in portfolio:
                track_icon = "⚡" if trade.track == 1 else "🛡️"
                entry_date = datetime.fromisoformat(trade.entry_date).date()
                days_held = (today - entry_date).days
                current = portfolio_prices.get(trade.symbol)
                if current is not None:
                    pnl = (current / trade.entry_price - 1) * 100
                    sign = "+" if pnl >= 0 else ""
                    lines.append(
                        f"• {trade.symbol} {track_icon} | ${trade.entry_price:,.2f} → ${current:,.2f}"
                        f" | {sign}{pnl:.1f}% | D+{days_held}"
                    )
                else:
                    lines.append(f"• {trade.symbol} {track_icon} | ${trade.entry_price:,.2f} | D+{days_held}")
        else:
            lines.append("💼 보유 포지션: 없음")

        return "\n".join(lines)

    def run_forever(self, fetcher: Callable[[str, str], list[Bar]]) -> None:
        # 텔레그램 명령어 polling 스레드 시작
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            from .telegram_handler import TelegramHandler
            handler = TelegramHandler(
                bot_token=self.config.telegram_bot_token,
                chat_id=self.config.telegram_chat_id,
                trade_store=self.trade_store,
                track1_symbols=self.config.track1_symbols,
                track2_symbols=self.config.track2_symbols,
            )
            handler.start()

        schedule.every().day.at("07:00").do(self.run_once, fetcher)

        while True:
            schedule.run_pending()
            time.sleep(60)


    def get_metrics_snapshot(self) -> RuntimeSnapshot:
        return self.metrics.snapshot()
