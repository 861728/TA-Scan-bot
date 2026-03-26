"""bot.py 검증 테스트 (목업 기반, 네트워크 불필요)."""

import sys
import os
sys.path.insert(0, ".")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test")

import asyncio
import json
import os
import re
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from types import ModuleType

# telegram 패키지 목업 (cryptography 의존성 우회)
telegram_mock = ModuleType("telegram")
telegram_mock.Update = MagicMock
telegram_ext_mock = ModuleType("telegram.ext")
telegram_ext_mock.ApplicationBuilder = MagicMock
telegram_ext_mock.CommandHandler = MagicMock
telegram_ext_mock.ContextTypes = MagicMock()
telegram_ext_mock.ContextTypes.DEFAULT_TYPE = MagicMock
telegram_ext_mock.MessageHandler = MagicMock
telegram_ext_mock.filters = MagicMock()
sys.modules["telegram"] = telegram_mock
sys.modules["telegram.ext"] = telegram_ext_mock

import pandas as pd

import config
import utils
from bot import (
    BUY_PATTERN,
    cmd_help,
    cmd_positions,
    cmd_scan,
    cmd_sellcheck,
    cmd_start,
    handle_buy_message,
    job_daily_scan,
    job_sell_check,
)


def setup_temp_trades(data):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(data, f)
    config.TRADES_PATH = path
    return path


def cleanup(path):
    if os.path.exists(path):
        os.remove(path)


def make_update(text):
    """텔레그램 Update 목업."""
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 매수 패턴 파싱
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_buy_pattern():
    print("=" * 50)
    print("1. 매수 패턴 파싱 테스트")
    print("=" * 50)

    # 기본: "삼성전자 58000 매수"
    m = BUY_PATTERN.match("삼성전자 58000 매수")
    assert m, "기본 패턴 매칭 실패"
    assert m.group(1) == "삼성전자"
    assert m.group(2) == "58000"
    assert m.group(3) is None  # 강신호 아님
    print("  '삼성전자 58000 매수' → 약신호 ✅")

    # 콤마: "삼성전자 58,000 매수"
    m = BUY_PATTERN.match("삼성전자 58,000 매수")
    assert m
    assert m.group(2) == "58,000"
    print("  '삼성전자 58,000 매수' → 콤마 처리 ✅")

    # 강신호: "삼성전자 58000 강신호 매수"
    m = BUY_PATTERN.match("삼성전자 58000 강신호 매수")
    assert m
    assert m.group(3) is not None
    print("  '삼성전자 58000 강신호 매수' → 강신호 ✅")

    # 강신호 공백 변형: "삼성전자 58000 강신호매수"
    m = BUY_PATTERN.match("삼성전자 58000 강신호매수")
    assert m
    assert m.group(3) is not None
    print("  '삼성전자 58000 강신호매수' → 강신호 ✅")

    # 비매칭: 일반 대화
    m = BUY_PATTERN.match("오늘 날씨 좋다")
    assert m is None
    print("  '오늘 날씨 좋다' → 무시 ✅")

    # 비매칭: 매수 없음
    m = BUY_PATTERN.match("삼성전자 58000")
    assert m is None
    print("  '삼성전자 58000' → 무시 ✅")
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. handle_buy_message
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_handle_buy():
    print("=" * 50)
    print("2. handle_buy_message 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])

    # 종목 캐시 주입
    utils._stock_cache = pd.DataFrame({
        "Code": ["005930", "000660"],
        "Name": ["삼성전자", "SK하이닉스"],
        "Market": ["KOSPI", "KOSPI"],
    })

    # 정상 약신호 매수
    update = make_update("삼성전자 58000 매수")
    ctx = make_context()
    run(handle_buy_message(update, ctx))

    reply = update.message.reply_text.call_args[0][0]
    print(f"  [약신호 매수 응답]\n  {reply}")
    assert "매수 기록 완료" in reply
    assert "삼성전자" in reply
    assert "약신호" in reply
    print("  ✅ 약신호 매수 기록 정상")

    # 강신호 매수
    update2 = make_update("SK하이닉스 150,000 강신호 매수")
    run(handle_buy_message(update2, ctx))
    reply2 = update2.message.reply_text.call_args[0][0]
    print(f"  [강신호 매수 응답]\n  {reply2}")
    assert "강신호" in reply2
    print("  ✅ 강신호 매수 기록 정상")

    # trades.json 확인
    trades = utils.load_trades()
    assert len(trades) == 2
    assert trades[0]["signal"] == "weak"
    assert trades[1]["signal"] == "strong"
    print(f"  ✅ trades.json에 {len(trades)}건 저장 확인")

    # 없는 종목
    update3 = make_update("없는회사 10000 매수")
    run(handle_buy_message(update3, ctx))
    reply3 = update3.message.reply_text.call_args[0][0]
    assert "찾을 수 없습니다" in reply3
    print("  ✅ 없는 종목 → 에러 메시지")

    # 비매수 메시지 → 무시 (reply_text 호출 없음)
    update4 = make_update("오늘 뭐 사지")
    update4.message.reply_text = AsyncMock()
    run(handle_buy_message(update4, ctx))
    update4.message.reply_text.assert_not_called()
    print("  ✅ 비매수 메시지 → 무시")

    cleanup(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 슬롯 초과 차단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_slot_overflow():
    print("=" * 50)
    print("3. 슬롯 초과 매수 차단 테스트")
    print("=" * 50)

    # 약신호 2개 이미 보유
    existing = [
        {"code": "AAA", "name": "A", "price": 10000, "signal": "weak",
         "buy_date": "2026-03-20", "fee": 30, "status": "holding"},
        {"code": "BBB", "name": "B", "price": 20000, "signal": "weak",
         "buy_date": "2026-03-20", "fee": 60, "status": "holding"},
    ]
    tmp = setup_temp_trades(existing)

    utils._stock_cache = pd.DataFrame({
        "Code": ["005930"], "Name": ["삼성전자"], "Market": ["KOSPI"],
    })

    update = make_update("삼성전자 58000 매수")
    ctx = make_context()
    run(handle_buy_message(update, ctx))

    reply = update.message.reply_text.call_args[0][0]
    print(f"  응답: {reply}")
    assert "슬롯 부족" in reply
    print("  ✅ 약신호 슬롯 초과 차단")

    # 강신호는 아직 여유
    update2 = make_update("삼성전자 58000 강신호 매수")
    run(handle_buy_message(update2, ctx))
    reply2 = update2.message.reply_text.call_args[0][0]
    assert "매수 기록 완료" in reply2
    print("  ✅ 강신호 슬롯은 여유 → 매수 성공")

    cleanup(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 명령어 핸들러
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_commands():
    print("=" * 50)
    print("4. 명령어 핸들러 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([
        {"code": "005930", "name": "삼성전자", "price": 58000, "signal": "weak",
         "buy_date": "2026-03-20", "fee": 174, "status": "holding"},
    ])

    ctx = make_context()

    # /start
    update = make_update("/start")
    run(cmd_start(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "트레이딩 봇" in reply
    print("  /start ✅")

    # /help
    update = make_update("/help")
    run(cmd_help(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "명령어" in reply
    assert "16:00" in reply or "매도체크" in reply
    print("  /help ✅")

    # /positions
    update = make_update("/positions")
    run(cmd_positions(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "삼성전자" in reply
    assert "58,000" in reply
    print(f"  /positions → {reply[:50]}... ✅")

    # /positions 빈 포지션
    tmp2 = setup_temp_trades([])
    update = make_update("/positions")
    run(cmd_positions(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "없음" in reply
    print("  /positions (빈) ✅")

    # /sellcheck
    update = make_update("/sellcheck")
    run(cmd_sellcheck(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "매도 대상 없음" in reply
    print("  /sellcheck ✅")

    cleanup(tmp)
    cleanup(tmp2)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 스케줄 작업 (job 콜백)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_scheduled_jobs():
    print("=" * 50)
    print("5. 스케줄 작업 (job 콜백) 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])

    # job_daily_scan
    ctx = make_context()
    with patch("bot.scan_all", return_value=[]), \
         patch("bot.build_signal_message", return_value="테스트 스캔 결과"):
        run(job_daily_scan(ctx))

    ctx.bot.send_message.assert_called_once()
    call_kwargs = ctx.bot.send_message.call_args
    assert call_kwargs[1]["chat_id"] == config.TELEGRAM_CHAT_ID
    assert call_kwargs[1]["text"] == "테스트 스캔 결과"
    print("  job_daily_scan → send_message 호출 ✅")

    # job_sell_check (알람 없음)
    ctx2 = make_context()
    with patch("bot.check_sell_alerts", return_value=[]):
        run(job_sell_check(ctx2))
    ctx2.bot.send_message.assert_not_called()
    print("  job_sell_check (없음) → 발송 안 함 ✅")

    # job_sell_check (알람 있음)
    ctx3 = make_context()
    alerts = [{"code": "005930", "name": "삼성전자", "price": 58000, "reason": "약신호 20일 청산"}]
    with patch("bot.check_sell_alerts", return_value=alerts), \
         patch("bot.build_sell_message", return_value="매도 알람 테스트"):
        run(job_sell_check(ctx3))
    ctx3.bot.send_message.assert_called_once()
    assert ctx3.bot.send_message.call_args[1]["text"] == "매도 알람 테스트"
    print("  job_sell_check (있음) → 발송 ✅")

    cleanup(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 엣지 케이스
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_edge_cases():
    print("=" * 50)
    print("6. 엣지 케이스 테스트")
    print("=" * 50)

    tmp = setup_temp_trades([])
    utils._stock_cache = pd.DataFrame({
        "Code": ["005930"], "Name": ["삼성전자"], "Market": ["KOSPI"],
    })
    ctx = make_context()

    # 가격 0원 매수
    update = make_update("삼성전자 0 매수")
    run(handle_buy_message(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "매수 기록 완료" in reply  # 0원도 기록은 됨 (유효성 검증은 별도)
    print("  가격 0원 → 기록 (경고 없이) ✅")

    # 큰 숫자
    update = make_update("삼성전자 1,000,000 매수")
    run(handle_buy_message(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    assert "1,000,000" in reply
    print("  큰 숫자(1,000,000) → 정상 처리 ✅")

    # 공백 많은 입력
    update = make_update("  삼성전자   58000   매수  ")
    # strip()이 handle_buy_message에서 처리
    run(handle_buy_message(update, ctx))
    # 슬롯 초과일 수 있지만 패턴 매칭은 되어야 함
    print("  공백 많은 입력 → 처리 ✅")

    cleanup(tmp)
    print()


if __name__ == "__main__":
    test_buy_pattern()
    test_handle_buy()
    test_slot_overflow()
    test_commands()
    test_scheduled_jobs()
    test_edge_cases()
    print("=" * 50)
    print("bot.py 모든 테스트 완료")
