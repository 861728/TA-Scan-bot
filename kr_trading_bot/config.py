# 한국 주식 트레이딩 봇 설정

# ── 텔레그램 ──
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

# ── 스캔 스케줄 ──
SCAN_HOUR = 16  # 매일 오후 4시
SCAN_MINUTE = 0

# ── 진입 조건 (베이스) ──
RSI_PERIOD = 14
RSI_THRESHOLD = 25          # RSI < 25
BB_PERIOD = 20              # 볼린저밴드 기간
BB_STD = 2                  # 볼린저밴드 표준편차 배수
VOLUME_AVG_PERIOD = 5       # 거래량 비교 기간
VOLUME_RATIO_MIN = 1.5      # 5일평균 대비 최소 배수
DROP_20D_THRESHOLD = -30    # 20일 낙폭 (%)
MA60_DROP_THRESHOLD = -30   # 60일 이동평균 대비 (%)

# ── 신호 등급 ──
# 약신호: 베이스 + (캔들 2%+ OR 거래량 20일평균 3배+)
WEAK_CANDLE_PCT = 2.0       # 양봉 몸통 최소 %
WEAK_VOLUME_AVG_PERIOD = 20
WEAK_VOLUME_RATIO = 3.0     # 20일평균 대비 배수

# 강신호: 약신호 + (BB폭 0.7+ OR 20일낙폭 -40%+ 캔들 3%+)
STRONG_BB_WIDTH = 0.7       # BB폭 기준
STRONG_DROP_20D = -40       # 20일 낙폭 (%)
STRONG_CANDLE_PCT = 3.0     # 캔들 몸통 최소 %

# ── 청산 규칙 ──
WEAK_HOLD_DAYS = 20         # 약신호 고정 청산일
STRONG_CHECK_DAY = 5        # 강신호 조기 체크일
STRONG_EARLY_EXIT_PCT = 0   # 5일 후 수익률 이하면 조기청산 (%)
STRONG_HOLD_DAYS = 20       # 강신호 최종 청산일

# ── 자본 규칙 ──
INITIAL_CAPITAL = 10_000_000  # 1,000만원
MAX_WEAK_SLOTS = 2            # 약신호 동시 보유 슬롯
MAX_STRONG_SLOTS = 1          # 강신호 동시 보유 슬롯
FEE_RATE = 0.003              # 수수료 0.3%

# ── 제외 업종 (네이버 금융 기준) ──
EXCLUDED_SECTORS = [
    "제약",
    "건강관리장비와용품",
    "화학",
    "핸드셋",
    "화장품",
]

# ── 데이터 ──
TRADES_PATH = "kr_trading_bot/trades.json"
