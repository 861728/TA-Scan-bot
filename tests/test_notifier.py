"""notifier.py 단위 테스트 — mock으로 텔레그램 API 대체"""

import os
import tempfile
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from us_trading_bot.notifier import (
    format_entry_alert, format_exit_alert,
    send_entry_alert, send_exit_alert, send_no_signal,
    cmd_buy, cmd_sell, cmd_positions, cmd_history,
    cmd_scan, cmd_sellcheck,
)
from us_trading_bot.database import init_db, add_position, add_trade, remove_position, get_position


# ── fixtures ─────────────────────────────────────────────

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def _make_update(text):
    """가짜 Update + Message 생성"""
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


SAMPLE_IND = {
    "rsi14": 28.3, "rsi5": 14.2, "bb_pct": 0.032,
    "drawdown": -24.1, "vol_ratio": 1.85,
}

SAMPLE_FULL_IND = {
    **SAMPLE_IND, "close": 234.50, "open": 230.0,
}


# ── format 함수 ──────────────────────────────────────────

def test_format_entry_alert():
    c = {"ticker": "TSLA", "close": 234.50, "rsi14": 28.3, "rsi5": 14.2,
         "bb_pct": 0.032, "drawdown": -24.1, "vol_ratio": 1.85}
    text = format_entry_alert(c)
    assert "🚨 진입 신호" in text
    assert "TSLA" in text
    assert "$234.50" in text
    assert "28.3" in text
    assert "-24.1%" in text
    assert "1.85x" in text


def test_format_exit_alert_peak():
    t = {"ticker": "TSLA", "exit_type": "peak", "close": 289.30,
         "hold_days": 23, "return_pct": 23.4}
    text = format_exit_alert(t)
    assert "✅ 청산 신호 (고점)" in text
    assert "23일" in text
    assert "+23.4%" in text


def test_format_exit_alert_forced():
    t = {"ticker": "TSLA", "exit_type": "forced", "close": 251.20,
         "hold_days": 80, "return_pct": 7.1}
    text = format_exit_alert(t)
    assert "⏰ 청산 신호 (80일 강제)" in text
    assert "80일" in text


def test_format_exit_alert_negative():
    t = {"ticker": "AMD", "exit_type": "forced", "close": 90.0,
         "hold_days": 80, "return_pct": -10.0}
    text = format_exit_alert(t)
    assert "-10.0%" in text


# ── send 함수 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_entry_alert():
    bot = AsyncMock()
    candidates = [{"ticker": "TSLA", "close": 234.50, "rsi14": 28.3,
                    "rsi5": 14.2, "bb_pct": 0.032, "drawdown": -24.1, "vol_ratio": 1.85}]
    await send_entry_alert(candidates, bot)
    bot.send_message.assert_called_once()
    text = bot.send_message.call_args.kwargs["text"]
    assert "TSLA" in text


@pytest.mark.asyncio
async def test_send_exit_alert():
    bot = AsyncMock()
    targets = [{"ticker": "TSLA", "exit_type": "peak", "close": 289.30,
                "hold_days": 23, "return_pct": 23.4}]
    await send_exit_alert(targets, bot)
    bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_no_signal():
    bot = AsyncMock()
    await send_no_signal(bot)
    bot.send_message.assert_called_once()
    assert "신호 없음" in bot.send_message.call_args.kwargs["text"]


@pytest.mark.asyncio
async def test_send_entry_alert_multiple():
    bot = AsyncMock()
    candidates = [
        {"ticker": "TSLA", "close": 234.50, "rsi14": 28.3,
         "rsi5": 14.2, "bb_pct": 0.032, "drawdown": -24.1, "vol_ratio": 1.85},
        {"ticker": "AMD", "close": 100.0, "rsi14": 25.0,
         "rsi5": 10.0, "bb_pct": 0.01, "drawdown": -30.0, "vol_ratio": 2.0},
    ]
    await send_entry_alert(candidates, bot)
    assert bot.send_message.call_count == 2


# ── /buy ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_buy_success(db_path):
    update = _make_update("/buy TSLA 234.50")
    ctx = _make_context(["TSLA", "234.50"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.fetch_single", return_value=SAMPLE_FULL_IND):
        await cmd_buy(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "✅ 매수 기록 완료" in reply
    assert "TSLA" in reply
    assert "$234.50" in reply
    assert get_position("TSLA", db_path) is not None


@pytest.mark.asyncio
async def test_cmd_buy_no_args(db_path):
    update = _make_update("/buy")
    ctx = _make_context([])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_buy(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "사용법" in reply


@pytest.mark.asyncio
async def test_cmd_buy_bad_price(db_path):
    update = _make_update("/buy TSLA abc")
    ctx = _make_context(["TSLA", "abc"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_buy(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "올바르지" in reply


@pytest.mark.asyncio
async def test_cmd_buy_duplicate(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    update = _make_update("/buy TSLA 234.50")
    ctx = _make_context(["TSLA", "234.50"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_buy(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "이미 보유" in reply


@pytest.mark.asyncio
async def test_cmd_buy_indicator_fail(db_path):
    update = _make_update("/buy MU 80.00")
    ctx = _make_context(["MU", "80.00"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.fetch_single", return_value=None):
        await cmd_buy(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "✅ 매수 기록 완료" in reply
    assert "지표 조회 실패" in reply
    assert get_position("MU", db_path) is not None


# ── /sell ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_sell_success(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    update = _make_update("/sell TSLA 250.00")
    ctx = _make_context(["TSLA", "250.00"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_sell(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "✅ 매도 기록 완료" in reply
    assert "+25.0%" in reply
    assert get_position("TSLA", db_path) is None


@pytest.mark.asyncio
async def test_cmd_sell_no_position(db_path):
    update = _make_update("/sell FAKE 100.00")
    ctx = _make_context(["FAKE", "100.00"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_sell(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "포지션이 없습니다" in reply


@pytest.mark.asyncio
async def test_cmd_sell_no_args(db_path):
    update = _make_update("/sell")
    ctx = _make_context([])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_sell(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "사용법" in reply


@pytest.mark.asyncio
async def test_cmd_sell_negative_return(db_path):
    add_position("AMD", "2026-03-01", 100.0, SAMPLE_IND, db_path)
    update = _make_update("/sell AMD 90.00")
    ctx = _make_context(["AMD", "90.00"])
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_sell(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "-10.0%" in reply


# ── /positions ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_positions_empty(db_path):
    update = _make_update("/positions")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_positions(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "보유 중인 포지션 없음" in reply


@pytest.mark.asyncio
async def test_cmd_positions_with_data(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    add_position("NVDA", "2026-03-10", 120.0, SAMPLE_IND, db_path)
    live = {
        "TSLA": {"close": 250.0, "open": 248.0, "rsi14": 50, "rsi5": 50,
                  "bb_pct": 0.5, "drawdown": -5, "vol_ratio": 1.0},
        "NVDA": {"close": 130.0, "open": 128.0, "rsi14": 55, "rsi5": 55,
                  "bb_pct": 0.6, "drawdown": -3, "vol_ratio": 1.1},
    }
    update = _make_update("/positions")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.fetch_all", return_value=live):
        await cmd_positions(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "📋 보유 포지션 (2개)" in reply
    assert "TSLA" in reply
    assert "NVDA" in reply
    assert "+25.0%" in reply


@pytest.mark.asyncio
async def test_cmd_positions_live_fail(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    update = _make_update("/positions")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.fetch_all", return_value={}):
        await cmd_positions(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "조회실패" in reply


# ── /history ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_history_empty(db_path):
    update = _make_update("/history")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_history(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "거래 내역 없음" in reply


@pytest.mark.asyncio
async def test_cmd_history_with_data(db_path):
    add_position("TSLA", "2026-03-01", 200.0, SAMPLE_IND, db_path)
    pos = get_position("TSLA", db_path)
    add_trade(pos, "2026-03-20", 250.0, "peak", db_path)
    remove_position("TSLA", db_path)

    add_position("AMD", "2026-01-01", 100.0, SAMPLE_IND, db_path)
    pos2 = get_position("AMD", db_path)
    add_trade(pos2, "2026-03-22", 90.0, "forced", db_path)
    remove_position("AMD", db_path)

    update = _make_update("/history")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path):
        await cmd_history(update, ctx)
    reply = update.message.reply_text.call_args[0][0]
    assert "📜 거래 내역 (총 2건)" in reply
    assert "승률: 50.0%" in reply
    assert "고점청산" in reply
    assert "강제청산" in reply


# ── /scan ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_scan_with_signals(db_path):
    candidates = [{"ticker": "TSLA", "close": 234.50, "rsi14": 28.3,
                    "rsi5": 14.2, "bb_pct": 0.032, "drawdown": -24.1, "vol_ratio": 1.85}]
    update = _make_update("/scan")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.scan_entries", return_value=candidates):
        await cmd_scan(update, ctx)
    # "스캔 중..." + 1 alert
    assert update.message.reply_text.call_count == 2
    texts = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("TSLA" in t for t in texts)


@pytest.mark.asyncio
async def test_cmd_scan_no_signals(db_path):
    update = _make_update("/scan")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.scan_entries", return_value=[]):
        await cmd_scan(update, ctx)
    texts = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("진입 신호 없음" in t for t in texts)


# ── /sellcheck ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_sellcheck_with_signals(db_path):
    targets = [{"ticker": "TSLA", "exit_type": "peak", "close": 289.30,
                "hold_days": 23, "return_pct": 23.4}]
    update = _make_update("/sellcheck")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.scan_exits", return_value=targets):
        await cmd_sellcheck(update, ctx)
    assert update.message.reply_text.call_count == 2


@pytest.mark.asyncio
async def test_cmd_sellcheck_no_signals(db_path):
    update = _make_update("/sellcheck")
    ctx = _make_context()
    with patch("us_trading_bot.notifier.DB_PATH", db_path), \
         patch("us_trading_bot.notifier.scan_exits", return_value=[]):
        await cmd_sellcheck(update, ctx)
    texts = [call[0][0] for call in update.message.reply_text.call_args_list]
    assert any("청산 신호 없음" in t for t in texts)
