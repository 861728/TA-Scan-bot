"""config.py 단위 테스트"""

import os
import importlib


def test_symbols_count():
    from us_trading_bot.config import SYMBOLS
    assert len(SYMBOLS) == 44


def test_no_duplicate_symbols():
    from us_trading_bot.config import SYMBOLS
    assert len(SYMBOLS) == len(set(SYMBOLS))


def test_entry_thresholds():
    from us_trading_bot.config import (
        ENTRY_RSI14_MAX, ENTRY_RSI5_MAX, ENTRY_BB_PCT_MAX,
        ENTRY_DRAWDOWN_MAX, ENTRY_VOL_RATIO_MIN,
    )
    assert ENTRY_RSI14_MAX == 31
    assert ENTRY_RSI5_MAX == 17
    assert ENTRY_BB_PCT_MAX == 0.05
    assert ENTRY_DRAWDOWN_MAX == -20
    assert ENTRY_VOL_RATIO_MIN == 1.3


def test_exit_thresholds():
    from us_trading_bot.config import (
        EXIT_RSI5_MIN, EXIT_RSI14_MIN, EXIT_BB_PCT_MIN, EXIT_MAX_HOLD_DAYS,
    )
    assert EXIT_RSI5_MIN == 80
    assert EXIT_RSI14_MIN == 70
    assert EXIT_BB_PCT_MIN == 0.90
    assert EXIT_MAX_HOLD_DAYS == 80


def test_telegram_env_defaults():
    from us_trading_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    # 환경변수 미설정 시 빈 문자열
    assert isinstance(TELEGRAM_BOT_TOKEN, str)
    assert isinstance(TELEGRAM_CHAT_ID, str)


def test_db_path_default():
    from us_trading_bot.config import DB_PATH
    assert DB_PATH.endswith("trades.db")


def test_db_path_env_override():
    os.environ["DB_PATH"] = "/tmp/test.db"
    import us_trading_bot.config as cfg
    importlib.reload(cfg)
    assert cfg.DB_PATH == "/tmp/test.db"
    # cleanup
    del os.environ["DB_PATH"]
    importlib.reload(cfg)
