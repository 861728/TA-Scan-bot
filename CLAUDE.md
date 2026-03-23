# M7-BottomFinder 프로젝트 컨텍스트

## 프로젝트 개요
나스닥 100 종목의 바닥권을 스캔하고 텔레그램으로 알림을 보내는 봇.
VPS(Ubuntu)에서 systemd로 운영 중. Python + yfinance 기반.

## 역할 분담
- **Claude.ai 채팅**: 방향 결정, 디렉션 작성, 개념 설명
- **Claude Code (여기)**: 실제 코드 수정, 커밋, 푸시
- **VPS**: 실제 실행 (`/opt/m7-bottomfinder/.venv/bin/python`)

## 주요 파일 구조
```
src/m7_bottomfinder/
├── app.py          # 설정 로드, 실행 진입점
├── runtime.py      # 스캔 → 알림 파이프라인, 메시지 조립(_build_alert_text)
├── alert_engine.py # 언제 보낼지 결정 (쿨타임, 중복, 점수)
├── backtest.py     # 백테스트 시뮬레이터
├── indicators.py   # 15개 기술 지표
├── providers.py    # yfinance 데이터 fetcher, KRW 환율
├── notifiers.py    # 텔레그램 전송
config.example.toml # 운영 파라미터
```

## 현재 운영 파라미터 (config.example.toml)
- symbols: M7 → **나스닥 100 전체로 변경 예정**
- timeframe: 15m → **1d로 변경 예정**
- interval_seconds: 600 → **86400으로 변경 예정**
- score_threshold: 5
- cooldown_minutes: 120
- 발송 시각: **매일 07:00 KST로 변경 예정** (schedule 라이브러리)

## 완료된 백테스트 결과 (일봉, 1년치)
- AAPL: 정밀도 76.5%, 평균반등 7.1%, 최대낙폭 -10.6%
- NVDA: 정밀도 80%, 평균반등 7.8%, 최대낙폭 -9.9%
- MSFT: 정밀도 71.4%, 평균반등 5.4%, 최대낙폭 -20.4%

---

## 지금 당장 할 작업 (우선순위 순)

### 1. backtest.py — 회복 기준 수정
**파일**: `src/m7_bottomfinder/backtest.py`
**함수**: `evaluate_signal`
**변경**:
```python
# 현재
if b.high >= entry:

# 변경
if b.close >= entry:
```
**이유**: 일봉 기준에서 고가 기준 회복은 너무 관대함. 종가 기준으로 현실적으로 수정.

### 2. config.example.toml — 운영 파라미터 변경
```toml
[runtime]
timeframe = "1d"
interval_seconds = 86400
symbols = [나스닥 100 전체 리스트]
```
나스닥 100 티커:
AAPL, MSFT, NVDA, AMZN, GOOG, GOOGL, META, TSLA, AVGO, COST,
NFLX, ASML, AMD, PEP, CSCO, ADBE, QCOM, INTU, AMAT, TXN,
BKNG, ISRG, MU, HON, VRTX, REGN, PANW, KLAC, LRCX, SNPS,
CDNS, ABNB, MELI, ORLY, FTNT, CTAS, MRVL, MNST, KDP, ODFL,
DXCM, TEAM, FAST, ROST, IDXX, BIIB, VRSK, GEHC, ON, NXPI,
CTSH, CPRT, PCAR, PAYX, DLTR, ANSS, FANG, ZS, CRWD, DDOG,
EBAY, EXC, ILMN, LULU, MAR, MCHP, MDLZ, MRNA, PYPL, SBUX,
WDAY, ADP, ALGN, GILD, MTCH, NDAQ, TTWO, WBD, ENPH, ENTG

### 3. app.py — 스케줄러 변경
**파일**: `src/m7_bottomfinder/app.py`
**변경**: `run_forever` 메서드를 매일 07:00 KST 실행으로 교체

```python
import schedule
import pytz

def run_forever(self, fetcher):
    def job():
        self.run_once(fetcher)

    schedule.every().day.at("07:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
```
**의존성 추가** (`pyproject.toml`): `schedule`, `pytz`

### 4. runtime.py — 알람 포맷 개선
**파일**: `src/m7_bottomfinder/runtime.py`
**함수**: `_build_alert_text`
**변경**: 충족된 지표만 표시, 이모지 포함 가독성 개선

목표 포맷:
```
🎯 AAPL 바닥 시그널 · 1d
━━━━━━━━━━━━━━━
💰 현재가: $247.87 (₩332,000)
⚡ 신호 강도: 6점

📊 핵심 근거
• CMF 자금유입
• MACD 다이버전스
• OBV 다이버전스

🤖 AI 분석
[ai_summary 내용]

⬆️ 이전 대비 신호 강화  ← 신호 강화 시에만 표시
```
- `results: list[IndicatorResult]` 파라미터 추가
- score > 0인 지표만 표시
- `run_cycle`에서 호출 시 `results` 인자 추가

---

## 작업 완료 후
VPS에서:
```bash
cd /opt/m7-bottomfinder
git pull
systemctl restart m7-bottomfinder
```
