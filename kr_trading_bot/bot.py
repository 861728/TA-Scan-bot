"""텔레그램 봇: 스케줄 스캔, 매수 기록, 매도 알람.

역할 분리:
- scanner.py: 스캔 로직 + 메시지 포맷 생성 (발송 X)
- bot.py: 텔레그램 수신/발송 + 스케줄 관리 (여기)
- utils.py: 지표 계산, 종목 매핑, 매수 기록 CRUD
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time

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
# 스케줄 작업 (JobQueue 콜백)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def job_daily_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    """매일 16:00 KST — 전종목 스캔 + 결과 발송."""
    logger.info("스케줄 스캔 시작")
    signals = scan_all()
    msg = build_signal_message(signals)
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
    logger.info(f"스캔 완료. 신호 {len(signals)}건 발송")


async def job_sell_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """매일 08:30 KST — 장 시작 전 매도 알람."""
    logger.info("매도 알람 체크 시작")
    alerts = check_sell_alerts()
    if alerts:
        msg = build_sell_message(alerts)
        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        logger.info(f"매도 알람 {len(alerts)}건 발송")
    else:
        logger.info("매도 대상 없음")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 명령어 핸들러
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "한국 주식 트레이딩 봇\n\n"
        "사용법:\n"
        "• 매수: '삼성전자 58000 매수'\n"
        "• 매수(강신호): '삼성전자 58000 강신호 매수'\n"
        "• 보유 조회: /positions\n"
        "• 수동 스캔: /scan\n"
        "• 매도 체크: /sellcheck\n"
        "• 도움말: /help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "명령어\n"
        "━━━━━━━━━━━━━━━\n"
        "• 매수: '삼성전자 58000 매수'\n"
        "• 매수(강신호): '삼성전자 58000 강신호 매수'\n"
        "• /positions — 보유 포지션\n"
        "• /scan — 수동 전종목 스캔\n"
        "• /sellcheck — 매도 대상 확인\n\n"
        f"슬롯: 약신호 {MAX_WEAK_SLOTS}개 / 강신호 {MAX_STRONG_SLOTS}개\n"
        f"스캔: 매일 {SCAN_HOUR}:{SCAN_MINUTE:02d} | 매도체크: 매일 08:30"
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active = get_active_trades()
    if not active:
        await update.message.reply_text("보유 포지션 없음")
        return

    lines = ["보유 포지션", "━━━━━━━━━━━━━━━"]
    for t in active:
        icon = "강" if t["signal"] == "strong" else "약"
        buy_date = datetime.strptime(t["buy_date"], "%Y-%m-%d")
        days_held = (datetime.now() - buy_date).days
        lines.append(f"• {t['name']}({t['code']}) [{icon}] | {t['price']:,.0f}원 | D+{days_held}")

    weak_used, strong_used = get_slot_counts()
    lines.append("")
    lines.append(f"슬롯: 약 {weak_used}/{MAX_WEAK_SLOTS} | 강 {strong_used}/{MAX_STRONG_SLOTS}")
    await update.message.reply_text("\n".join(lines))


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("스캔 시작... (수 분 소요)")
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
# 자연어 매수 입력
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# "삼성전자 58000 매수" or "삼성전자 58,000 강신호 매수"
BUY_PATTERN = re.compile(r"^(.+?)\s+([\d,]+)\s*(강신호\s*)?매수$")


async def handle_buy_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    match = BUY_PATTERN.match(text)
    if not match:
        return

    name = match.group(1).strip()
    price = float(match.group(2).replace(",", ""))
    signal = "strong" if match.group(3) else "weak"

    # 종목명 → 코드
    code = name_to_code(name)
    if code is None:
        await update.message.reply_text(f"'{name}' 종목을 찾을 수 없습니다.")
        return

    # 슬롯 체크
    weak_used, strong_used = get_slot_counts()
    if signal == "weak" and weak_used >= MAX_WEAK_SLOTS:
        await update.message.reply_text(f"약신호 슬롯 부족 ({weak_used}/{MAX_WEAK_SLOTS})")
        return
    if signal == "strong" and strong_used >= MAX_STRONG_SLOTS:
        await update.message.reply_text(f"강신호 슬롯 부족 ({strong_used}/{MAX_STRONG_SLOTS})")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    trade = add_trade(code, name, price, signal, today)
    signal_label = "강신호" if signal == "strong" else "약신호"

    await update.message.reply_text(
        f"매수 기록 완료\n"
        f"• {name}({code})\n"
        f"• {price:,.0f}원 [{signal_label}]\n"
        f"• 수수료 {trade['fee']:,.0f}원"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # 명령어
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("sellcheck", cmd_sellcheck))

    # 자연어 매수
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_message))

    # 스케줄 (python-telegram-bot 내장 JobQueue 사용)
    job_queue = app.job_queue
    # 매일 16:00 KST 전종목 스캔
    scan_time = time(hour=SCAN_HOUR, minute=SCAN_MINUTE, tzinfo=None)
    job_queue.run_daily(job_daily_scan, time=scan_time, name="daily_scan")
    # 매일 08:30 KST 매도 알람
    sell_time = time(hour=8, minute=30, tzinfo=None)
    job_queue.run_daily(job_sell_check, time=sell_time, name="sell_check")

    logger.info(
        f"봇 시작 | 스캔: {SCAN_HOUR}:{SCAN_MINUTE:02d} | 매도체크: 08:30"
    )
    app.run_polling()


if __name__ == "__main__":
    main()
