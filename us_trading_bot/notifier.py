"""
US Trading Bot - Notifier

텔레그램 알람 발송 + 명령어 핸들러
- python-telegram-bot (v20+) async API 사용
"""

from datetime import date

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
)

from us_trading_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DB_PATH
from us_trading_bot.database import (
    init_db, add_position, get_position, get_positions,
    remove_position, add_trade, get_trades,
)
from us_trading_bot.indicators import fetch_single, fetch_all
from us_trading_bot.scanner import scan_entries, scan_exits


# ── 알람 메시지 포맷 ─────────────────────────────────────

def format_entry_alert(c):
    sign = "+" if c["drawdown"] >= 0 else ""
    return (
        f"🚨 진입 신호\n"
        f"종목: {c['ticker']}\n"
        f"현재가: ${c['close']:,.2f}\n"
        f"RSI14: {c['rsi14']} | RSI5: {c['rsi5']}\n"
        f"BB%: {c['bb_pct']} | 낙폭: {sign}{c['drawdown']}%\n"
        f"거래량비율: {c['vol_ratio']}x"
    )


def format_exit_alert(t):
    if t["exit_type"] == "peak":
        header = "✅ 청산 신호 (고점)"
    else:
        header = "⏰ 청산 신호 (80일 강제)"
    sign = "+" if t["return_pct"] >= 0 else ""
    return (
        f"{header}\n"
        f"종목: {t['ticker']}\n"
        f"보유일: {t['hold_days']}일\n"
        f"현재가: ${t['close']:,.2f}\n"
        f"예상수익률: {sign}{t['return_pct']}%"
    )


# ── 알람 발송 함수 ───────────────────────────────────────

async def send_entry_alert(candidates, bot):
    for c in candidates:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=format_entry_alert(c))


async def send_exit_alert(targets, bot):
    for t in targets:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=format_exit_alert(t))


async def send_no_signal(bot):
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text="📊 스캔 완료 — 진입/청산 신호 없음",
    )


# ── 텔레그램 명령어 핸들러 ────────────────────────────────

async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용법: /us_buy TSLA 234.50"""
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("사용법: /us_buy 종목 가격\n예: /us_buy TSLA 234.50")
        return

    ticker = context.args[0].upper()
    try:
        price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ 가격이 올바르지 않습니다.")
        return

    if get_position(ticker, DB_PATH):
        await update.message.reply_text(f"❌ {ticker}은(는) 이미 보유 중입니다.")
        return

    ind = fetch_single(ticker)
    indicators = ind or {}

    add_position(
        ticker,
        str(date.today()),
        price,
        {
            "rsi14": indicators.get("rsi14"),
            "rsi5": indicators.get("rsi5"),
            "bb_pct": indicators.get("bb_pct"),
            "drawdown": indicators.get("drawdown"),
            "vol_ratio": indicators.get("vol_ratio"),
        },
        DB_PATH,
    )

    lines = [f"✅ 매수 기록 완료", f"종목: {ticker}", f"진입가: ${price:,.2f}"]
    if ind:
        dd_sign = "+" if ind["drawdown"] >= 0 else ""
        lines.append(f"RSI14: {ind['rsi14']} | RSI5: {ind['rsi5']}")
        lines.append(f"BB%: {ind['bb_pct']} | 낙폭: {dd_sign}{ind['drawdown']}%")
        lines.append(f"거래량비율: {ind['vol_ratio']}x")
    else:
        lines.append("(지표 조회 실패 — 가격만 저장)")

    await update.message.reply_text("\n".join(lines))


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """사용법: /us_sell TSLA 289.30"""
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("사용법: /us_sell 종목 가격\n예: /us_sell TSLA 289.30")
        return

    ticker = context.args[0].upper()
    try:
        exit_price = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ 가격이 올바르지 않습니다.")
        return

    pos = get_position(ticker, DB_PATH)
    if not pos:
        await update.message.reply_text(f"❌ {ticker} 포지션이 없습니다.")
        return

    result = add_trade(pos, str(date.today()), exit_price, "manual", DB_PATH)
    remove_position(ticker, DB_PATH)

    sign = "+" if result["return_pct"] >= 0 else ""
    await update.message.reply_text(
        f"✅ 매도 기록 완료\n"
        f"종목: {ticker}\n"
        f"진입가: ${pos['entry_price']:,.2f} → 청산가: ${exit_price:,.2f}\n"
        f"보유일: {result['hold_days']}일 | 수익률: {sign}{result['return_pct']}%"
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/us_positions — 보유 포지션 조회"""
    positions = get_positions(DB_PATH)
    if not positions:
        await update.message.reply_text("보유 중인 포지션 없음")
        return

    today = date.today()
    lines = [f"📋 보유 포지션 ({len(positions)}개)"]

    tickers = [p["ticker"] for p in positions]
    live = fetch_all(tickers)

    for p in positions:
        entry_dt = date.fromisoformat(str(p["entry_date"]))
        hold_days = (today - entry_dt).days
        ticker = p["ticker"]
        ind = live.get(ticker)
        if ind:
            cur_price = ind["close"]
            ret = round((cur_price - p["entry_price"]) / p["entry_price"] * 100, 1)
            sign = "+" if ret >= 0 else ""
            lines.append(
                f"• {ticker} | 진입가 ${p['entry_price']:,.2f} | "
                f"{hold_days}일째 | 현재가 ${cur_price:,.2f} | {sign}{ret}%"
            )
        else:
            lines.append(
                f"• {ticker} | 진입가 ${p['entry_price']:,.2f} | "
                f"{hold_days}일째 | 현재가 조회실패"
            )

    await update.message.reply_text("\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/us_history — 전체 거래 내역"""
    trades = get_trades(DB_PATH)
    if not trades:
        await update.message.reply_text("거래 내역 없음")
        return

    total = len(trades)
    wins = sum(1 for t in trades if t["return_pct"] > 0)
    win_rate = round(wins / total * 100, 1)
    avg_ret = round(sum(t["return_pct"] for t in trades) / total, 1)
    avg_sign = "+" if avg_ret >= 0 else ""

    lines = [
        f"📜 거래 내역 (총 {total}건)",
        f"승률: {win_rate}% | 평균수익률: {avg_sign}{avg_ret}%",
        "──────────────",
    ]

    exit_labels = {"peak": "고점청산", "forced": "강제청산", "manual": "수동청산"}
    for t in trades:
        sign = "+" if t["return_pct"] >= 0 else ""
        label = exit_labels.get(t["exit_type"], t["exit_type"])
        lines.append(f"• {t['ticker']} | {sign}{t['return_pct']}% | {t['hold_days']}일 | {label}")

    await update.message.reply_text("\n".join(lines))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/us_scan — 수동 전종목 스캔"""
    await update.message.reply_text("🔍 스캔 중...")
    candidates = scan_entries(DB_PATH)
    if candidates:
        for c in candidates:
            await update.message.reply_text(format_entry_alert(c))
    else:
        await update.message.reply_text("📊 스캔 완료 — 진입 신호 없음")


async def cmd_sellcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/us_sellcheck — 보유 종목 매도 신호 확인"""
    await update.message.reply_text("🔍 매도 체크 중...")
    targets = scan_exits(DB_PATH)
    if targets:
        for t in targets:
            await update.message.reply_text(format_exit_alert(t))
    else:
        await update.message.reply_text("📊 매도 체크 완료 — 청산 신호 없음")


# ── Application 빌드 ─────────────────────────────────────

def build_app(token=None):
    """텔레그램 봇 Application 생성 (polling 용)"""
    token = token or TELEGRAM_BOT_TOKEN
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("us_buy", cmd_buy))
    app.add_handler(CommandHandler("us_sell", cmd_sell))
    app.add_handler(CommandHandler("us_positions", cmd_positions))
    app.add_handler(CommandHandler("us_history", cmd_history))
    app.add_handler(CommandHandler("us_scan", cmd_scan))
    app.add_handler(CommandHandler("us_sellcheck", cmd_sellcheck))
    return app
