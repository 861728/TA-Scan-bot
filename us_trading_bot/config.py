"""
US Trading Bot - Configuration

환경변수:
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    텔레그램 채팅 ID
  DB_PATH             SQLite DB 경로 (기본: trades.db)
"""

import os
from pathlib import Path

# ── 프로젝트 경로 ──────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "trades.db"))

# ── 텔레그램 ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── 대상 종목 (44개) ─────────────────────────────────────
SYMBOLS = [
    "PLTR", "TTD", "AMD", "TSLA", "MU", "COHR", "LITE", "VRT", "ON", "FCX",
    "NVDA", "MRVL", "DDOG", "MPWR", "MELI", "RCL", "UAL", "WDC", "ALGN", "ZS",
    "MGM", "URI", "CIEN", "CRWD", "WYNN", "UBER", "LRCX", "TER", "TEAM", "OKTA",
    "ALB", "ANET", "GNRC", "FSLR", "NXPI", "FIX", "AMAT", "CCL", "STX", "AVGO",
    "NOW", "KLAC", "AXON", "DAL",
]

# ── 진입 조건 임계값 ─────────────────────────────────────
ENTRY_RSI14_MAX = 31
ENTRY_RSI5_MAX = 17
ENTRY_BB_PCT_MAX = 0.05
ENTRY_DRAWDOWN_MAX = -20       # % (음수)
ENTRY_VOL_RATIO_MIN = 1.3

# ── 청산 조건 임계값 ─────────────────────────────────────
# 고점 신호
EXIT_RSI5_MIN = 80
EXIT_RSI14_MIN = 70
EXIT_BB_PCT_MIN = 0.90

# 강제 청산 일수
EXIT_MAX_HOLD_DAYS = 80

# ── yfinance 데이터 설정 ─────────────────────────────────
DATA_PERIOD = "2y"             # 52주 고점 계산에 최소 1년 필요
DATA_INTERVAL = "1d"

# ── 스케줄러 ─────────────────────────────────────────────
SCAN_TIME_KST = "06:00"       # 한국 시간 (= US ET 16:30 장마감)
TIMEZONE = "Asia/Seoul"
