"""전종목 스캔 → 신호 감지 → 텔레그램 발송."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

from config import (
    MAX_STRONG_SLOTS,
    MAX_WEAK_SLOTS,
    STRONG_CHECK_DAY,
    STRONG_EARLY_EXIT_PCT,
    STRONG_HOLD_DAYS,
    WEAK_HOLD_DAYS,
)
from utils import (
    add_trade,
    calc_candle_body_pct,
    calc_drop_from_high,
    calc_rsi,
    calc_volume_ratio,
    classify_signal,
    close_trade,
    code_to_name,
    filter_excluded_sectors,
    get_active_trades,
    get_all_stocks,
    get_sector_map,
    get_slot_counts,
    load_trades,
)

logger = logging.getLogger(__name__)


def fetch_ohlcv(code: str, days: int = 120) -> pd.DataFrame | None:
    """종목코드로 OHLCV 데이터 가져오기."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df is None or df.empty or len(df) < 60:
            return None
        return df
    except Exception as e:
        logger.debug(f"{code} 데이터 실패: {e}")
        return None


def scan_all() -> list[dict]:
    """전종목 스캔 → 신호 발생 종목 리스트 반환.

    Returns:
        [{"code": "005930", "name": "삼성전자", "signal": "weak"|"strong",
          "price": 58000, "rsi": 22.3, "drop_20d": -32.1, ...}, ...]
    """
    logger.info("전종목 스캔 시작")
    stocks = get_all_stocks()

    # 업종 필터링
    logger.info("업종 필터링 중...")
    sector_map = get_sector_map()
    stocks = filter_excluded_sectors(stocks, sector_map)
    logger.info(f"필터 후 종목 수: {len(stocks)}")

    # 슬롯 확인
    weak_used, strong_used = get_slot_counts()
    weak_avail = MAX_WEAK_SLOTS - weak_used
    strong_avail = MAX_STRONG_SLOTS - strong_used

    signals = []

    for _, row in stocks.iterrows():
        code = row["Code"]
        name = row["Name"]

        df = fetch_ohlcv(code)
        if df is None:
            continue

        signal_type = classify_signal(df)
        if signal_type is None:
            continue

        # 슬롯 부족하면 스킵
        if signal_type == "weak" and weak_avail <= 0:
            continue
        if signal_type == "strong" and strong_avail <= 0:
            continue

        close = df["Close"].iloc[-1]
        open_ = df["Open"].iloc[-1]
        rsi_val = calc_rsi(df["Close"]).iloc[-1]
        drop_20d = calc_drop_from_high(df["Close"], 20).iloc[-1]
        candle_pct = calc_candle_body_pct(df["Open"], df["Close"]).iloc[-1]
        vol_ratio = calc_volume_ratio(df["Volume"], 5).iloc[-1]

        info = {
            "code": code,
            "name": name,
            "signal": signal_type,
            "price": close,
            "rsi": round(rsi_val, 1),
            "drop_20d": round(drop_20d, 1),
            "candle_pct": round(candle_pct, 1),
            "vol_ratio": round(vol_ratio, 1),
        }
        signals.append(info)
        logger.info(f"신호 감지: {name}({code}) {signal_type} ₩{close:,.0f}")

        # 슬롯 차감
        if signal_type == "weak":
            weak_avail -= 1
        else:
            strong_avail -= 1

    logger.info(f"스캔 완료. 신호 {len(signals)}건")
    return signals


def build_signal_message(signals: list[dict]) -> str:
    """텔레그램 발송용 메시지 생성."""
    today = datetime.now().strftime("%Y-%m-%d")
    sep = "━━━━━━━━━━━━━━━"

    lines = [f"📅 {today} 스캔 결과", sep]

    if not signals:
        lines.append("신호 없음")
        return "\n".join(lines)

    strong = [s for s in signals if s["signal"] == "strong"]
    weak = [s for s in signals if s["signal"] == "weak"]

    if strong:
        lines.append("🔥 강신호")
        for s in strong:
            lines.append(
                f"• {s['name']}({s['code']}) ₩{s['price']:,.0f}\n"
                f"  RSI {s['rsi']} | 낙폭 {s['drop_20d']}% | "
                f"캔들 +{s['candle_pct']}% | 거래량 {s['vol_ratio']}x"
            )

    if weak:
        lines.append("⚡ 약신호")
        for s in weak:
            lines.append(
                f"• {s['name']}({s['code']}) ₩{s['price']:,.0f}\n"
                f"  RSI {s['rsi']} | 낙폭 {s['drop_20d']}% | "
                f"캔들 +{s['candle_pct']}% | 거래량 {s['vol_ratio']}x"
            )

    # 보유 포지션 요약
    active = get_active_trades()
    if active:
        lines.append("")
        lines.append("💼 보유 포지션")
        for t in active:
            icon = "🔥" if t["signal"] == "strong" else "⚡"
            buy_date = datetime.strptime(t["buy_date"], "%Y-%m-%d")
            days_held = (datetime.now() - buy_date).days
            lines.append(f"• {t['name']} {icon} | ₩{t['price']:,.0f} | D+{days_held}")

    return "\n".join(lines)


def check_sell_alerts() -> list[dict]:
    """매도 알람 체크. 청산 대상 반환.

    - 약신호: 20일 고정 청산
    - 강신호: 5일 체크 → 수익률 0% 이하면 조기청산, 아니면 20일 청산
    """
    today = datetime.now().date()
    alerts = []

    for t in get_active_trades():
        buy_date = datetime.strptime(t["buy_date"], "%Y-%m-%d").date()
        days_held = (today - buy_date).days

        if t["signal"] == "weak":
            if days_held >= WEAK_HOLD_DAYS:
                alerts.append({**t, "reason": f"약신호 {WEAK_HOLD_DAYS}일 청산"})

        elif t["signal"] == "strong":
            if days_held >= STRONG_HOLD_DAYS:
                alerts.append({**t, "reason": f"강신호 {STRONG_HOLD_DAYS}일 청산"})
            elif days_held >= STRONG_CHECK_DAY:
                # 5일 체크: 현재가 확인 필요
                df = fetch_ohlcv(t["code"], days=10)
                if df is not None and not df.empty:
                    current = df["Close"].iloc[-1]
                    pnl = (current / t["price"] - 1) * 100
                    if pnl <= STRONG_EARLY_EXIT_PCT:
                        alerts.append({
                            **t,
                            "current_price": current,
                            "pnl_pct": round(pnl, 1),
                            "reason": f"강신호 5일 조기청산 (수익률 {pnl:.1f}%)",
                        })

    return alerts


def build_sell_message(alerts: list[dict]) -> str:
    """매도 알람 메시지."""
    if not alerts:
        return ""
    lines = ["⏰ 매도 알람"]
    for a in alerts:
        lines.append(f"• {a['name']}({a['code']}) ₩{a['price']:,.0f} | {a['reason']}")
    return "\n".join(lines)
