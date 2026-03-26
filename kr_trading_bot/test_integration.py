"""통합 테스트: config → utils → scanner → bot 전체 흐름."""

import sys
sys.path.insert(0, ".")

import json
import os
import tempfile
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

# telegram 목업
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

import asyncio
import numpy as np
import pandas as pd

import config
import utils
from scanner import build_signal_message, build_sell_message, check_sell_alerts, scan_all
from bot import (
    BUY_PATTERN,
    handle_buy_message,
    cmd_positions,
    job_daily_scan,
    job_sell_check,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_update(text):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def make_ohlcv(closes, volumes=None, opens=None):
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    if opens is None:
        opens = [c * 0.99 for c in closes]
    highs = [max(o, c) * 1.01 for o, c in zip(opens, closes)]
    lows = [min(o, c) * 0.98 for o, c in zip(opens, closes)]
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. import 체인 검증
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_import_chain():
    print("=" * 50)
    print("1. import 체인 검증")
    print("=" * 50)

    # config
    assert hasattr(config, "RSI_THRESHOLD")
    assert hasattr(config, "TELEGRAM_BOT_TOKEN")
    assert hasattr(config, "MAX_WEAK_SLOTS")
    print("  config.py ✅")

    # utils
    from utils import calc_rsi, calc_bollinger, classify_signal, name_to_code
    from utils import add_trade, load_trades, get_slot_counts, check_base_conditions
    print("  utils.py ✅")

    # scanner
    from scanner import scan_all, build_signal_message, check_sell_alerts, build_sell_message
    print("  scanner.py ✅")

    # bot
    from bot import cmd_start, cmd_help, cmd_positions, cmd_scan, cmd_sellcheck
    from bot import handle_buy_message, job_daily_scan, job_sell_check
    print("  bot.py ✅")

    print("  → 전체 import 체인 정상")
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. trades.json 없는 상태에서 첫 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_first_run_no_trades():
    print("=" * 50)
    print("2. trades.json 없는 상태 첫 실행")
    print("=" * 50)

    # 존재하지 않는 경로 설정
    tmp_dir = tempfile.mkdtemp()
    nonexistent = os.path.join(tmp_dir, "subdir", "trades.json")
    config.TRADES_PATH = nonexistent

    assert not os.path.exists(nonexistent), "파일이 이미 존재함"
    print(f"  경로: {nonexistent} (존재하지 않음)")

    # load_trades → 빈 리스트
    trades = utils.load_trades()
    assert trades == []
    print("  load_trades() → [] ✅")

    # get_slot_counts → (0, 0)
    weak, strong = utils.get_slot_counts()
    assert (weak, strong) == (0, 0)
    print("  get_slot_counts() → (0, 0) ✅")

    # get_active_trades → []
    active = utils.get_active_trades()
    assert active == []
    print("  get_active_trades() → [] ✅")

    # add_trade → 파일 자동 생성
    utils._stock_cache = pd.DataFrame({
        "Code": ["005930"], "Name": ["삼성전자"], "Market": ["KOSPI"],
    })
    trade = utils.add_trade("005930", "삼성전자", 58000, "weak", "2026-03-26")
    assert os.path.exists(nonexistent), "trades.json 자동 생성 실패"
    print(f"  add_trade() → 파일 자동 생성 ✅")

    with open(nonexistent) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["code"] == "005930"
    print(f"  저장 내용: {data[0]['name']} {data[0]['price']}원 ✅")

    # 정리
    os.remove(nonexistent)
    os.rmdir(os.path.dirname(nonexistent))
    os.rmdir(tmp_dir)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 전체 흐름: 매수 → 저장 → 매도 알람
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_full_flow():
    print("=" * 50)
    print("3. 매수 → 저장 → 매도 알람 전체 흐름")
    print("=" * 50)

    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(tmp, "w") as f:
        json.dump([], f)
    config.TRADES_PATH = tmp

    utils._stock_cache = pd.DataFrame({
        "Code": ["005930", "000660"],
        "Name": ["삼성전자", "SK하이닉스"],
        "Market": ["KOSPI", "KOSPI"],
    })
    ctx = make_context()

    # Step 1: 약신호 매수
    print("  [Step 1] 약신호 매수")
    update1 = make_update("삼성전자 58000 매수")
    run(handle_buy_message(update1, ctx))
    reply1 = update1.message.reply_text.call_args[0][0]
    assert "매수 기록 완료" in reply1
    assert "약신호" in reply1
    print(f"    → {reply1.splitlines()[0]} ✅")

    # Step 2: 강신호 매수
    print("  [Step 2] 강신호 매수")
    update2 = make_update("SK하이닉스 150,000 강신호 매수")
    run(handle_buy_message(update2, ctx))
    reply2 = update2.message.reply_text.call_args[0][0]
    assert "강신호" in reply2
    print(f"    → {reply2.splitlines()[0]} ✅")

    # Step 3: trades.json 확인
    print("  [Step 3] trades.json 확인")
    trades = utils.load_trades()
    assert len(trades) == 2
    assert trades[0]["signal"] == "weak" and trades[0]["name"] == "삼성전자"
    assert trades[1]["signal"] == "strong" and trades[1]["name"] == "SK하이닉스"
    print(f"    → {len(trades)}건 저장 ✅")

    # Step 4: /positions 확인
    print("  [Step 4] /positions")
    update3 = make_update("/positions")
    run(cmd_positions(update3, ctx))
    reply3 = update3.message.reply_text.call_args[0][0]
    assert "삼성전자" in reply3 and "SK하이닉스" in reply3
    print(f"    → 2종목 표시 ✅")

    # Step 5: 매수일을 21일 전으로 변경 → 매도 알람
    print("  [Step 5] 매도 알람 (약신호 20일 경과)")
    trades[0]["buy_date"] = (datetime.now() - timedelta(days=21)).strftime("%Y-%m-%d")
    utils.save_trades(trades)

    alerts = check_sell_alerts()
    assert len(alerts) >= 1
    assert any(a["code"] == "005930" for a in alerts)
    print(f"    → 삼성전자 매도 알람 발생 ✅")

    # Step 6: 강신호 5일 조기청산 체크
    print("  [Step 6] 강신호 5일 조기청산")
    trades[1]["buy_date"] = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    utils.save_trades(trades)

    # 현재가 142500 → 수익률 -5%
    mock_df = make_ohlcv([142500] * 10)
    with patch("scanner.fetch_ohlcv", return_value=mock_df):
        alerts2 = check_sell_alerts()
    hynix_alerts = [a for a in alerts2 if a["code"] == "000660"]
    assert len(hynix_alerts) == 1
    assert "조기청산" in hynix_alerts[0]["reason"]
    print(f"    → SK하이닉스 조기청산 알람 (수익률 {hynix_alerts[0]['pnl_pct']}%) ✅")

    # Step 7: 매도 메시지 → bot 발송
    print("  [Step 7] bot 매도 알람 발송")
    ctx2 = make_context()
    with patch("bot.check_sell_alerts", return_value=alerts2), \
         patch("bot.build_sell_message", return_value="매도알람테스트"):
        run(job_sell_check(ctx2))
    ctx2.bot.send_message.assert_called_once()
    print(f"    → send_message 호출 ✅")

    os.remove(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 강신호 슬롯1 꽉 찬 상태 차단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_strong_slot_full():
    print("=" * 50)
    print("4. 강신호 슬롯1 꽉 찬 상태 차단")
    print("=" * 50)

    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    existing = [
        {"code": "000660", "name": "SK하이닉스", "price": 150000, "signal": "strong",
         "buy_date": "2026-03-20", "fee": 450, "status": "holding"},
    ]
    with open(tmp, "w") as f:
        json.dump(existing, f)
    config.TRADES_PATH = tmp

    utils._stock_cache = pd.DataFrame({
        "Code": ["005930"], "Name": ["삼성전자"], "Market": ["KOSPI"],
    })

    weak, strong = utils.get_slot_counts()
    print(f"  현재 슬롯: 약 {weak}/{config.MAX_WEAK_SLOTS}, 강 {strong}/{config.MAX_STRONG_SLOTS}")

    # 강신호 매수 시도
    update = make_update("삼성전자 58000 강신호 매수")
    ctx = make_context()
    run(handle_buy_message(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    print(f"  응답: {reply}")
    assert "슬롯 부족" in reply
    print("  ✅ 강신호 슬롯 초과 차단")

    # 약신호는 통과
    update2 = make_update("삼성전자 58000 매수")
    run(handle_buy_message(update2, ctx))
    reply2 = update2.message.reply_text.call_args[0][0]
    assert "매수 기록 완료" in reply2
    print("  ✅ 약신호는 정상 매수")

    os.remove(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 약신호 슬롯2 꽉 찬 상태 차단
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_weak_slot_full():
    print("=" * 50)
    print("5. 약신호 슬롯2 꽉 찬 상태 차단")
    print("=" * 50)

    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    existing = [
        {"code": "AAA", "name": "종목A", "price": 10000, "signal": "weak",
         "buy_date": "2026-03-20", "fee": 30, "status": "holding"},
        {"code": "BBB", "name": "종목B", "price": 20000, "signal": "weak",
         "buy_date": "2026-03-20", "fee": 60, "status": "holding"},
    ]
    with open(tmp, "w") as f:
        json.dump(existing, f)
    config.TRADES_PATH = tmp

    utils._stock_cache = pd.DataFrame({
        "Code": ["005930"], "Name": ["삼성전자"], "Market": ["KOSPI"],
    })

    weak, strong = utils.get_slot_counts()
    print(f"  현재 슬롯: 약 {weak}/{config.MAX_WEAK_SLOTS}, 강 {strong}/{config.MAX_STRONG_SLOTS}")

    # 약신호 매수 시도
    update = make_update("삼성전자 58000 매수")
    ctx = make_context()
    run(handle_buy_message(update, ctx))
    reply = update.message.reply_text.call_args[0][0]
    print(f"  응답: {reply}")
    assert "슬롯 부족" in reply
    print("  ✅ 약신호 슬롯 초과 차단")

    # 강신호는 통과
    update2 = make_update("삼성전자 58000 강신호 매수")
    run(handle_buy_message(update2, ctx))
    reply2 = update2.message.reply_text.call_args[0][0]
    assert "매수 기록 완료" in reply2
    print("  ✅ 강신호는 정상 매수")

    os.remove(tmp)
    print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    test_import_chain()
    test_first_run_no_trades()
    test_full_flow()
    test_strong_slot_full()
    test_weak_slot_full()
    print("=" * 50)
    print("통합 테스트 전체 통과")
    print()
    print("=" * 50)
    print("VPS 배포 후 체크리스트 (네트워크 필요)")
    print("=" * 50)
    print("[ ] FDR: fdr.StockListing('KOSPI'/'KOSDAQ') 전종목 로드")
    print("[ ] FDR: fdr.DataReader('005930', ...) OHLCV 수신")
    print("[ ] 네이버: get_sector_map() 업종 크롤링")
    print("[ ] 업종 필터: 제약/화학 등 실제 종목 제외 확인")
    print("[ ] 텔레그램: 봇 토큰으로 send_message 발송")
    print("[ ] 텔레그램: 자연어 매수 입력 수신")
    print("[ ] 스케줄: 16:00 scan 자동 실행")
    print("[ ] 스케줄: 08:30 매도 알람 자동 실행")
    print("[ ] 전종목 스캔 소요 시간 측정 (타임아웃 확인)")
