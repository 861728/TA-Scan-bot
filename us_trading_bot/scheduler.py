"""
US Trading Bot - Scheduler

APScheduler + python-telegram-bot polling 통합
- 06:00 KST: 전종목 진입 스캔
- 06:05 KST: 보유 종목 청산 체크
- 텔레그램 명령어 polling (블로킹)
"""

import logging
import asyncio
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from us_trading_bot.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DB_PATH, TIMEZONE,
)
from us_trading_bot.database import init_db
from us_trading_bot.scanner import scan_entries, scan_exits
from us_trading_bot.notifier import (
    send_entry_alert, send_exit_alert, send_no_signal, build_app,
)

logger = logging.getLogger(__name__)


async def scan_and_alert(bot):
    """매일 06:00 KST — 전종목 진입 스캔"""
    logger.info("진입 스캔 시작")
    try:
        candidates = scan_entries(DB_PATH)
        if candidates:
            logger.info("진입 신호 %d건 발견", len(candidates))
            await send_entry_alert(candidates, bot)
        else:
            logger.info("진입 신호 없음")
            await send_no_signal(bot)
    except Exception:
        logger.exception("진입 스캔 중 에러")


async def exit_check_and_alert(bot):
    """매일 06:05 KST — 보유 종목 청산 체크"""
    logger.info("청산 체크 시작")
    try:
        targets = scan_exits(DB_PATH)
        if targets:
            logger.info("청산 신호 %d건 발견", len(targets))
            await send_exit_alert(targets, bot)
        else:
            logger.info("청산 신호 없음")
    except Exception:
        logger.exception("청산 체크 중 에러")


def create_scheduler(bot):
    """APScheduler 생성 + 06:00, 06:05 작업 등록"""
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        scan_and_alert,
        trigger=CronTrigger(hour=6, minute=0, timezone=TIMEZONE),
        args=[bot],
        id="scan_entries",
        name="진입 스캔 (06:00 KST)",
    )
    scheduler.add_job(
        exit_check_and_alert,
        trigger=CronTrigger(hour=6, minute=5, timezone=TIMEZONE),
        args=[bot],
        id="exit_check",
        name="청산 체크 (06:05 KST)",
    )
    return scheduler


def main():
    """메인 실행: DB 초기화 → 스케줄러 → 봇 polling"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN 환경변수가 설정되지 않았습니다.")
        sys.exit(1)
    if not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    logger.info("DB 초기화")
    init_db(DB_PATH)

    app = build_app(TELEGRAM_BOT_TOKEN)
    bot = app.bot

    scheduler = create_scheduler(bot)
    scheduler.start()
    logger.info("스케줄러 시작 (06:00 진입스캔, 06:05 청산체크)")

    logger.info("텔레그램 봇 polling 시작")
    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료")


if __name__ == "__main__":
    main()
