"""공통 유틸리티: 지표 계산, 업종 필터, 종목명↔코드 매핑."""

from __future__ import annotations

import json
import re
from math import isnan
from pathlib import Path

import FinanceDataReader as fdr
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

import config as config
from config import (
    BB_PERIOD,
    BB_STD,
    DROP_20D_THRESHOLD,
    EXCLUDED_SECTORS,
    FEE_RATE,
    MA60_DROP_THRESHOLD,
    RSI_PERIOD,
    RSI_THRESHOLD,
    STRONG_BB_WIDTH,
    STRONG_CANDLE_PCT,
    STRONG_DROP_20D,
    VOLUME_AVG_PERIOD,
    VOLUME_RATIO_MIN,
    WEAK_CANDLE_PCT,
    WEAK_VOLUME_AVG_PERIOD,
    WEAK_VOLUME_RATIO,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 기술적 지표 계산
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_bollinger(series: pd.Series, period: int = BB_PERIOD, std: int = BB_STD):
    """볼린저밴드 (중심, 상단, 하단, BB폭) 반환."""
    mid = series.rolling(window=period).mean()
    std_val = series.rolling(window=period).std()
    upper = mid + std * std_val
    lower = mid - std * std_val
    width = (upper - lower) / mid  # BB폭
    return mid, upper, lower, width


def calc_ma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calc_volume_ratio(volume: pd.Series, period: int) -> pd.Series:
    """현재 거래량 / N일 평균 거래량."""
    avg = volume.rolling(window=period).mean()
    return volume / avg


def calc_drop_from_high(close: pd.Series, period: int) -> pd.Series:
    """N일 고점 대비 낙폭 (%)."""
    high = close.rolling(window=period).max()
    return (close / high - 1) * 100


def calc_candle_body_pct(open_: pd.Series, close: pd.Series) -> pd.Series:
    """양봉 몸통 비율 (%)."""
    return (close / open_ - 1) * 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 종목 리스트 & 업종 필터
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_all_stocks() -> pd.DataFrame:
    """코스피+코스닥 전종목 리스트 (Code, Name, Market)."""
    kospi = fdr.StockListing("KOSPI")[["Code", "Name"]].assign(Market="KOSPI")
    kosdaq = fdr.StockListing("KOSDAQ")[["Code", "Name"]].assign(Market="KOSDAQ")
    return pd.concat([kospi, kosdaq], ignore_index=True)


def get_sector_map() -> dict[str, str]:
    """네이버 금융에서 종목코드 → 업종명 매핑을 가져온다.
    (코스피+코스닥 업종 페이지 크롤링)
    """
    sector_map: dict[str, str] = {}
    urls = [
        "https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no=",
    ]
    # 네이버 업종 목록 페이지
    list_url = "https://finance.naver.com/sise/sise_group.naver?type=upjong"
    try:
        resp = requests.get(list_url, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select("a[href*='sise_group_detail']")
        for link in links:
            sector_name = link.text.strip()
            href = link.get("href", "")
            no_match = re.search(r"no=(\d+)", href)
            if not no_match:
                continue
            no = no_match.group(1)
            detail_url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={no}"
            try:
                dresp = requests.get(detail_url, timeout=10)
                dresp.encoding = "euc-kr"
                dsoup = BeautifulSoup(dresp.text, "html.parser")
                rows = dsoup.select("table.type_5 tr")
                for row in rows:
                    code_link = row.select_one("a[href*='main.naver?code=']")
                    if code_link:
                        code_match = re.search(r"code=(\d+)", code_link.get("href", ""))
                        if code_match:
                            sector_map[code_match.group(1)] = sector_name
            except Exception:
                continue
    except Exception:
        pass
    return sector_map


def filter_excluded_sectors(stocks: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame:
    """제외 업종에 해당하는 종목을 걸러낸다."""
    excluded_codes = set()
    for code, sector in sector_map.items():
        for excl in EXCLUDED_SECTORS:
            if excl in sector:
                excluded_codes.add(code)
                break
    return stocks[~stocks["Code"].isin(excluded_codes)].reset_index(drop=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 종목명 ↔ 코드 매핑 (텔레그램 자연어 매수용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_stock_cache: pd.DataFrame | None = None


def _load_stock_cache() -> pd.DataFrame:
    global _stock_cache
    if _stock_cache is None:
        _stock_cache = get_all_stocks()
    return _stock_cache


def name_to_code(name: str) -> str | None:
    """종목명 → 종목코드 (예: '삼성전자' → '005930')."""
    df = _load_stock_cache()
    match = df[df["Name"] == name]
    if match.empty:
        # 부분 매칭
        match = df[df["Name"].str.contains(name, na=False)]
    if match.empty:
        return None
    return match.iloc[0]["Code"]


def code_to_name(code: str) -> str | None:
    """종목코드 → 종목명."""
    df = _load_stock_cache()
    match = df[df["Code"] == code]
    return match.iloc[0]["Name"] if not match.empty else None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 신호 판별
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_base_conditions(df: pd.DataFrame) -> bool:
    """베이스 6개 조건 모두 충족 여부.
    df: 최소 60일 이상의 OHLCV 데이터 (columns: Open, High, Low, Close, Volume)
    """
    if len(df) < 60:
        return False

    close = df["Close"]
    open_ = df["Open"]
    volume = df["Volume"]

    # 1. RSI < 25
    rsi = calc_rsi(close)
    if pd.isna(rsi.iloc[-1]) or rsi.iloc[-1] >= RSI_THRESHOLD:
        return False

    # 2. 전일 볼린저밴드 하단 이탈
    _, _, lower, _ = calc_bollinger(close)
    if pd.isna(lower.iloc[-2]) or close.iloc[-2] >= lower.iloc[-2]:
        return False

    # 3. 당일 양봉 (종가 > 시가)
    if close.iloc[-1] <= open_.iloc[-1]:
        return False

    # 4. 거래량 5일평균 1.5배 이상
    vol_ratio = calc_volume_ratio(volume, VOLUME_AVG_PERIOD)
    if pd.isna(vol_ratio.iloc[-1]) or vol_ratio.iloc[-1] < VOLUME_RATIO_MIN:
        return False

    # 5. 20일 낙폭 -30% 이하
    drop_20 = calc_drop_from_high(close, 20)
    if pd.isna(drop_20.iloc[-1]) or drop_20.iloc[-1] > DROP_20D_THRESHOLD:
        return False

    # 6. 60일 이동평균 대비 -30% 이하
    ma60 = calc_ma(close, 60)
    if pd.isna(ma60.iloc[-1]):
        return False
    ma60_diff = (close.iloc[-1] / ma60.iloc[-1] - 1) * 100
    if ma60_diff > MA60_DROP_THRESHOLD:
        return False

    return True


def classify_signal(df: pd.DataFrame) -> str | None:
    """베이스 통과 후 신호 등급 판별. 'strong' / 'weak' / None."""
    if not check_base_conditions(df):
        return None

    close = df["Close"]
    open_ = df["Open"]
    volume = df["Volume"]

    candle_pct = calc_candle_body_pct(open_, close).iloc[-1]
    vol_ratio_20 = calc_volume_ratio(volume, WEAK_VOLUME_AVG_PERIOD).iloc[-1]
    _, _, _, bb_width = calc_bollinger(close)
    drop_20 = calc_drop_from_high(close, 20).iloc[-1]

    # 약신호 조건: 캔들 2%+ OR 거래량 20일 3배+
    is_weak = candle_pct >= WEAK_CANDLE_PCT or vol_ratio_20 >= WEAK_VOLUME_RATIO
    if not is_weak:
        return None

    # 강신호 조건: BB폭 0.7+ OR (20일낙폭 -40%+ AND 캔들 3%+)
    bb_w = bb_width.iloc[-1] if not pd.isna(bb_width.iloc[-1]) else 0
    is_strong = bb_w >= STRONG_BB_WIDTH or (drop_20 <= STRONG_DROP_20D and candle_pct >= STRONG_CANDLE_PCT)
    if is_strong:
        return "strong"

    return "weak"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 매수 기록 관리 (trades.json)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_trades() -> list[dict]:
    path = Path(config.TRADES_PATH)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_trades(trades: list[dict]) -> None:
    path = Path(config.TRADES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


def add_trade(code: str, name: str, price: float, signal: str, date: str) -> dict:
    """매수 기록 추가. 수수료 반영."""
    trade = {
        "code": code,
        "name": name,
        "price": price,
        "signal": signal,      # 'weak' or 'strong'
        "buy_date": date,
        "fee": round(price * FEE_RATE, 2),
        "status": "holding",
    }
    trades = load_trades()
    trades.append(trade)
    save_trades(trades)
    return trade


def get_active_trades() -> list[dict]:
    """현재 보유 중인 포지션."""
    return [t for t in load_trades() if t["status"] == "holding"]


def get_slot_counts() -> tuple[int, int]:
    """(약신호 사용 슬롯, 강신호 사용 슬롯) 반환."""
    active = get_active_trades()
    weak = sum(1 for t in active if t["signal"] == "weak")
    strong = sum(1 for t in active if t["signal"] == "strong")
    return weak, strong


def close_trade(code: str, sell_price: float, sell_date: str) -> dict | None:
    """매도 처리. 수익률 계산 후 status='closed'."""
    trades = load_trades()
    for t in trades:
        if t["code"] == code and t["status"] == "holding":
            t["sell_price"] = sell_price
            t["sell_date"] = sell_date
            t["sell_fee"] = round(sell_price * FEE_RATE, 2)
            t["pnl_pct"] = round((sell_price / t["price"] - 1) * 100 - FEE_RATE * 100 * 2, 2)
            t["status"] = "closed"
            save_trades(trades)
            return t
    return None
