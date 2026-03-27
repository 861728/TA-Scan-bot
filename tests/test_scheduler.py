"""scheduler.py 단위 테스트"""

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from us_trading_bot.scheduler import (
    scan_and_alert, exit_check_and_alert, create_scheduler, main,
)
from us_trading_bot.database import init_db, add_position


# ── fixtures ─────────────────────────────────────────────

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


SAMPLE_IND = {"rsi14": 28.0, "rsi5": 14.0, "bb_pct": 0.03, "drawdown": -22.0, "vol_ratio": 1.5}


# ── scan_and_alert ───────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_and_alert_with_signals(db_path):
    bot = AsyncMock()
    candidates = [{"ticker": "TSLA", "close": 234.50, "rsi14": 28.3,
                    "rsi5": 14.2, "bb_pct": 0.032, "drawdown": -24.1, "vol_ratio": 1.85}]
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_entries", return_value=candidates):
        await scan_and_alert(bot)
    bot.send_message.assert_called_once()
    assert "TSLA" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_scan_and_alert_no_signals(db_path):
    bot = AsyncMock()
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_entries", return_value=[]):
        await scan_and_alert(bot)
    bot.send_message.assert_called_once()
    assert "신호 없음" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_scan_and_alert_exception(db_path):
    bot = AsyncMock()
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_entries", side_effect=Exception("network error")):
        await scan_and_alert(bot)
    # 에러 시 봇 메시지 안 보냄 (로그만)
    bot.send_message.assert_not_called()


# ── exit_check_and_alert ─────────────────────────────────

@pytest.mark.asyncio
async def test_exit_check_with_signals(db_path):
    bot = AsyncMock()
    targets = [{"ticker": "TSLA", "exit_type": "peak", "close": 289.30,
                "hold_days": 23, "return_pct": 23.4}]
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_exits", return_value=targets):
        await exit_check_and_alert(bot)
    bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_exit_check_no_signals(db_path):
    bot = AsyncMock()
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_exits", return_value=[]):
        await exit_check_and_alert(bot)
    # 청산 신호 없으면 조용히 패스
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_exit_check_exception(db_path):
    bot = AsyncMock()
    with patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.scan_exits", side_effect=Exception("fail")):
        await exit_check_and_alert(bot)
    bot.send_message.assert_not_called()


# ── create_scheduler ─────────────────────────────────────

def test_create_scheduler_has_two_jobs():
    bot = AsyncMock()
    scheduler = create_scheduler(bot)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 2
    job_ids = {j.id for j in jobs}
    assert "scan_entries" in job_ids
    assert "exit_check" in job_ids


def test_create_scheduler_timezone():
    bot = AsyncMock()
    scheduler = create_scheduler(bot)
    assert str(scheduler.timezone) == "Asia/Seoul"


def test_create_scheduler_job_triggers():
    bot = AsyncMock()
    scheduler = create_scheduler(bot)
    jobs = {j.id: j for j in scheduler.get_jobs()}

    scan_trigger = jobs["scan_entries"].trigger
    exit_trigger = jobs["exit_check"].trigger

    # CronTrigger 필드 확인
    scan_fields = {f.name: str(f) for f in scan_trigger.fields}
    assert scan_fields["hour"] == "6"
    assert scan_fields["minute"] == "0"

    exit_fields = {f.name: str(f) for f in exit_trigger.fields}
    assert exit_fields["hour"] == "6"
    assert exit_fields["minute"] == "5"


# ── main ─────────────────────────────────────────────────

def test_main_exits_without_token():
    with patch("us_trading_bot.scheduler.TELEGRAM_BOT_TOKEN", ""), \
         pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_exits_without_chat_id():
    with patch("us_trading_bot.scheduler.TELEGRAM_BOT_TOKEN", "fake-token"), \
         patch("us_trading_bot.scheduler.TELEGRAM_CHAT_ID", ""), \
         pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_initializes_db(db_path):
    """main()이 init_db 호출하는지 확인 (polling 전에 중단)"""
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    mock_app.run_polling = MagicMock(side_effect=KeyboardInterrupt)

    with patch("us_trading_bot.scheduler.TELEGRAM_BOT_TOKEN", "fake-token"), \
         patch("us_trading_bot.scheduler.TELEGRAM_CHAT_ID", "12345"), \
         patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.build_app", return_value=mock_app), \
         patch("us_trading_bot.scheduler.create_scheduler", return_value=MagicMock()), \
         patch("us_trading_bot.scheduler.init_db") as mock_init:
        try:
            main()
        except KeyboardInterrupt:
            pass
    mock_init.assert_called_once_with(db_path)


def test_main_starts_scheduler_and_polling(db_path):
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    mock_app.run_polling = MagicMock()

    with patch("us_trading_bot.scheduler.TELEGRAM_BOT_TOKEN", "fake-token"), \
         patch("us_trading_bot.scheduler.TELEGRAM_CHAT_ID", "12345"), \
         patch("us_trading_bot.scheduler.DB_PATH", db_path), \
         patch("us_trading_bot.scheduler.build_app", return_value=mock_app), \
         patch("us_trading_bot.scheduler.init_db"), \
         patch("us_trading_bot.scheduler.create_scheduler") as mock_sched:
        mock_scheduler = MagicMock()
        mock_sched.return_value = mock_scheduler
        main()
    mock_scheduler.start.assert_called_once()
    mock_app.run_polling.assert_called_once_with(drop_pending_updates=True)
    mock_scheduler.shutdown.assert_called_once_with(wait=False)
