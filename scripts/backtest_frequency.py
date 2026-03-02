"""
S&P 100 백테스트 - 현재 설정(그룹핑 + Volume 필터) 기준 신호 빈도 분석
Usage: python scripts/backtest_frequency.py [--symbols N] [--years N]
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from m7_bottomfinder.backtest import BacktestSimulator
from m7_bottomfinder.data_layer import Bar, normalize_timestamp
from m7_bottomfinder.indicator_engine import IndicatorEngine, IndicatorGroup
from m7_bottomfinder.indicators import default_phase2_indicators

SP100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "WMT",
    "NFLX", "JNJ", "ABBV", "BAC", "CRM", "CVX", "MRK", "ORCL", "KO", "AMD",
    "PEP", "TMO", "ACN", "MCD", "CSCO", "LIN", "TXN", "ABT", "PM", "ADBE",
    "IBM", "DHR", "GE", "CAT", "QCOM", "INTU", "VZ", "NEE", "ISRG", "BKNG",
    "SPGI", "RTX", "PFE", "AMGN", "HON", "LOW", "TJX", "CMCSA", "UBER", "AMAT",
    "GS", "MS", "UNP", "BLK", "SYK", "VRTX", "AXP", "GILD", "DE", "ADI",
    "REGN", "C", "BSX", "PLD", "SCHW", "CB", "MDT", "PANW", "MU", "ETN",
    "SO", "DUK", "ZTS", "CI", "SLB", "WFC", "ICE", "COP", "CME", "LRCX",
    "SBUX", "BMY", "MMM", "ELV", "AON", "MDLZ", "KLAC", "MCO", "PGR", "NOC",
]


def build_engine() -> IndicatorEngine:
    return IndicatorEngine(
        indicators=default_phase2_indicators(),
        score_threshold=5,
        ai_call_threshold=6,
        min_s_hits_for_ai=2,
        s_tier_names={"wvf_spike", "volume_capitulation", "obv_divergence"},
        min_volume_multiple=1.5,
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
    )


def fetch_daily_bars(symbol: str, years: int) -> list[Bar]:
    try:
        import yfinance as yf
        period = f"{years}y"
        hist = yf.Ticker(symbol).history(period=period, interval="1d")
        bars = []
        for idx, row in hist.iterrows():
            bars.append(Bar(
                timestamp=normalize_timestamp(idx.to_pydatetime()),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            ))
        return bars
    except Exception as e:
        print(f"  [{symbol}] fetch 실패: {e}", file=sys.stderr)
        return []


def iso_week(ts: datetime) -> str:
    return ts.date().isocalendar()[:2]  # (year, week)


def iso_month(ts: datetime) -> str:
    return (ts.year, ts.month)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=int, default=20,
                        help="분석할 종목 수 (기본 20, 전체 100)")
    parser.add_argument("--years", type=int, default=10,
                        help="백테스트 기간 (년, 기본 10)")
    args = parser.parse_args()

    symbols = SP100[: args.symbols]
    engine = build_engine()
    simulator = BacktestSimulator(
        engine=engine,
        cooldown_bars=5,       # 일봉 기준 5일(1주) 쿨다운
        strengthen_delta=3,
        precision_target_pct=3.0,
        lookahead_bars=20,     # 20거래일(약 1달) 선행 평가
    )

    all_signals: list[tuple[str, datetime, str]] = []  # (symbol, ts, direction)
    symbol_stats: dict[str, int] = {}
    total_bars = 0
    fetch_errors = 0

    print(f"\n{'='*60}")
    print(f"  M7 BottomFinder 백테스트 — {args.years}년 일봉 / {len(symbols)}개 종목")
    print(f"  조건: grouped_score≥5, volume≥1.5×avg, 그룹핑 상한 적용")
    print(f"{'='*60}\n")

    for i, symbol in enumerate(symbols, 1):
        print(f"[{i:3d}/{len(symbols)}] {symbol:6s} ", end="", flush=True)
        bars = fetch_daily_bars(symbol, args.years)
        if len(bars) < 60:
            print(f"→ 데이터 부족 ({len(bars)}봉)")
            fetch_errors += 1
            continue

        total_bars += len(bars)
        signals, _, report = simulator.run(bars, warmup_bars=60)
        bullish_sigs = [s for s in signals if str(s.direction) in ("SignalDirection.BULLISH", "bullish")]
        symbol_stats[symbol] = len(bullish_sigs)

        for s in bullish_sigs:
            all_signals.append((symbol, s.timestamp, "BULLISH"))

        precision_str = f"{report.precision*100:.0f}%" if report.signal_count > 0 else "N/A"
        print(f"→ {len(bullish_sigs):3d}신호  precision={precision_str}  avg_rebound={report.avg_rebound_pct:+.1f}%")

        if i < len(symbols):
            time.sleep(0.3)

    if not all_signals:
        print("\n[결과] 신호 없음 — 데이터 접근 실패 가능성")
        return

    # ── 빈도 분석 ──────────────────────────────────────────────
    weeks: dict = defaultdict(int)
    months: dict = defaultdict(int)
    years_d: dict = defaultdict(int)

    for _, ts, _ in all_signals:
        weeks[iso_week(ts)] += 1
        months[iso_month(ts)] += 1
        years_d[ts.year] += 1

    total_weeks = len(weeks)
    total_months = len(months)
    total_signals = len(all_signals)

    avg_per_week = total_signals / total_weeks if total_weeks else 0
    avg_per_month = total_signals / total_months if total_months else 0
    avg_per_year = total_signals / args.years

    # 상위 신호 발생 종목
    top5 = sorted(symbol_stats.items(), key=lambda x: x[1], reverse=True)[:5]

    print(f"\n{'='*60}")
    print(f"  📊 집계 결과 ({args.years}년 / {len(symbols)}종목)")
    print(f"{'='*60}")
    print(f"  총 신호 수        : {total_signals:,}개")
    print(f"  분석 봉 수        : {total_bars:,}봉")
    print(f"  데이터 오류 종목  : {fetch_errors}개")
    print()
    print(f"  ┌─────────────────────────────┐")
    print(f"  │  평균 신호 빈도              │")
    print(f"  │  주간 : {avg_per_week:5.1f}개/주           │")
    print(f"  │  월간 : {avg_per_month:5.1f}개/월           │")
    print(f"  │  연간 : {avg_per_year:5.0f}개/년           │")
    print(f"  └─────────────────────────────┘")
    print()

    print("  연도별 신호 수:")
    for yr in sorted(years_d):
        bar = "█" * min(int(years_d[yr] / max(years_d.values()) * 30), 30)
        print(f"    {yr}: {bar:30s} {years_d[yr]:3d}개")

    print()
    print("  신호 많은 상위 5종목:")
    for sym, cnt in top5:
        print(f"    {sym:6s}: {cnt}개 ({cnt/args.years:.1f}/년)")

    # 주간 분포
    weekly_counts = sorted(weeks.values())
    q1 = weekly_counts[len(weekly_counts) // 4]
    median = weekly_counts[len(weekly_counts) // 2]
    q3 = weekly_counts[3 * len(weekly_counts) // 4]
    max_wk = max(weekly_counts)
    zero_wks = sum(1 for v in weekly_counts if v == 0)

    print()
    print(f"  주간 신호 분포 (전체 {total_weeks}주):")
    print(f"    신호 없는 주    : {zero_wks}주 ({zero_wks/total_weeks*100:.0f}%)")
    print(f"    Q1 / 중앙값 / Q3: {q1} / {median} / {q3}개")
    print(f"    최대 주         : {max_wk}개 (위기 구간)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
