"""텔레그램 봇: 스케줄 스캔, 매수 기록, 매도 알람."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    MAX_STRONG_SLOTS,
    MAX_WEAK_SLOTS,
    SCAN_HOUR,
    SCAN_MINUTE,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from scanner import (
    build_sell_message,
    build_signal_message,
    check_sell_alerts,
    scan_all,
)
from utils import (
    add_trade,
    close_trade,
    get_active_trades,
    get_slot_counts,
    name_to_code,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 스케줄 작업
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def scheduled_scan(app) -> None:
    """매일 오후 4시 전종목 스캔 + 매도 체크."""
    logger.info("스케줄 스캔 시작")

    # 매도 알람
    sell_alerts = check_sell_alerts()
    if sell_alerts:
        msg = build_sell_message(sell_alerts)
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

    # 전종목 스캔
    signals = scan_all()
    msg = build_signal_message(signals)
    await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)

    logger.info("스케줄 스캔 완료")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 텔레그램 명령어 핸들러
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "한국 주식 트레이딩 봇 🇰🇷\n\n"
        "사용법:\n"
        "• 매수 기록: '삼성전자 58000 매수'\n"
        "• 보유 조회: /positions\n"
        "• 수동 스캔: /scan\n"
        "• 도움말: /help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 명령어\n"
        "━━━━━━━━━━━━━━━\n"
        "• 매수: '삼성전자 58000 매수'\n"
        "• 보유 조회: /positions\n"
        "• 수동 스캔: /scan\n"
        "• 매도 체크: /sellcheck\n\n"
        f"슬롯: 약신호 {MAX_WEAK_SLOTS}개 / 강신호 {MAX_STRONG_SLOTS}개\n"
        f"스캔: 매일 {SCAN_HOUR}:{SCAN_MINUTE:02d}"
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active = get_active_trades()
    if not active:
        await update.message.reply_text("💼 보유 포지션 없음")
        return

    lines = ["💼 보유 포지션", "━━━━━━━━━━━━━━━"]
    for t in active:
        icon = "🔥" if t["signal"] == "strong" else "⚡"
        buy_date = datetime.strptime(t["buy_date"], "%Y-%m-%d")
        days_held = (datetime.now() - buy_date).days
        lines.append(f"• {t['name']} {icon} | ₩{t['price']:,.0f} | D+{days_held}")

    weak_used, strong_used = get_slot_counts()
    lines.append("")
    lines.append(f"슬롯: 약신호 {weak_used}/{MAX_WEAK_SLOTS} | 강신호 {strong_used}/{MAX_STRONG_SLOTS}")
    await update.message.reply_text("\n".join(lines))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 스캔 시작... (수 분 소요)")
    signals = scan_all()
    msg = build_signal_message(signals)
    await update.message.reply_text(msg)


async def cmd_sellcheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    alerts = check_sell_alerts()
    if not alerts:
        await update.message.reply_text("매도 대상 없음")
        return
    msg = build_sell_message(alerts)
    await update.message.reply_text(msg)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 자연어 매수 입력 처리
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 패턴: "삼성전자 58000 매수" or "삼성전자 58,000 매수"
BUY_PATTERN = re.compile(r"^(.+?)\s+([\d,]+)\s*매수$")


async def handle_buy_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    match = BUY_PATTERN.match(text)
    if not match:
        return  # 매수 메시지가 아님 → 무시

    name = match.group(1).strip()
    price = float(match.group(2).replace(",", ""))

    # 종목명 → 코드 매핑
    code = name_to_code(name)
    if code is None:
        await update.message.reply_text(f"❌ '{name}' 종목을 찾을 수 없습니다.")
        return

    # 신호 타입 결정 (기본 weak, 사용자가 지정 가능하게 확장 가능)
    # 현재는 수동 매수이므로 weak로 기록
    signal = "weak"
    today = datetime.now().strftime("%Y-%m-%d")

    trade = add_trade(code, name, price, signal, today)
    await update.message.reply_text(
        f"✅ 매수 기록\n"
        f"• {name}({code})\n"
        f"• ₩{price:,.0f}\n"
        f"• {signal} 신호\n"
        f"• 수수료 ₩{trade['fee']:,.0f}"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 명령어 핸들러
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("sellcheck", cmd_sellcheck))

    # 자연어 매수 메시지 핸들러
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_message))

    # 스케줄러 (매일 오후 4시)
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        lambda: app.create_task(scheduled_scan(app)),
        "cron",
        hour=SCAN_HOUR,
        minute=SCAN_MINUTE,
    )
    scheduler.start()

    logger.info(f"봇 시작. 스캔 스케줄: 매일 {SCAN_HOUR}:{SCAN_MINUTE:02d} KST")
    app.run_polling()


if __name__ == "__main__":
    main()
